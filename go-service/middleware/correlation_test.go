package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetTraceStorage() {
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestIsValidCorrelationID(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	makeStr := func(ch byte, n int) string {
		return strings.Repeat(string([]byte{ch}), n)
	}

	tests := []struct {
		name string
		id   string
		ok   bool
	}{
		{"valid with hyphen", "abcde-12345", true}, // length 11
		{"valid underscores", "valid_id_12345", true},
		{"valid min length 10", makeStr('a', 10), true},
		{"valid max length 100", makeStr('a', 100), true},
		{"too short", "short", false},
		{"too long", makeStr('a', 101), false},
		{"invalid char dollar", "abc$123456", false},
		{"invalid unicode", "ümlaut-12345", false},
		{"spaces not allowed", "abc defghij", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.ok, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_IsValid(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	id1 := generateCorrelationID()
	require.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1), "generated ID should be valid")

	// Generate a second ID and expect it to be valid and likely different.
	time.Sleep(time.Millisecond) // help ensure different timestamp component
	id2 := generateCorrelationID()
	require.NotEmpty(t, id2)
	assert.True(t, isValidCorrelationID(id2), "generated ID should be valid")
	assert.NotEqual(t, id1, id2, "generated IDs should typically be different")
}

func TestExtractOrGenerateID_UsesExistingValidHeader(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	existing := "valid-abcdef1234"
	req.Header.Set(CorrelationIDHeader, existing)

	id := ExtractOrGenerateID(req)
	assert.Equal(t, existing, id)
}

func TestExtractOrGenerateID_GeneratesWhenMissing(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	id := ExtractOrGenerateID(req)
	require.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateID_GeneratesWhenInvalidHeader(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	req.Header.Set(CorrelationIDHeader, "short") // invalid
	id := ExtractOrGenerateID(req)
	require.NotEmpty(t, id)
	assert.NotEqual(t, "short", id)
	assert.True(t, isValidCorrelationID(id))
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	req := httptest.NewRequest(http.MethodPost, "/submit", nil)
	cid := "valid-abcdef123456"
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces(cid)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodPost, tr.Method)
	assert.Equal(t, "/submit", tr.Path)
	assert.Equal(t, cid, tr.CorrelationID)
	assert.Equal(t, http.StatusCreated, tr.Status)
}

func TestTrackRequest_IgnoresWhenHeaderMissing(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	req := httptest.NewRequest(http.MethodGet, "/nonesuch", nil)

	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestStoreTrace_TriggersCleanupOfOldTraces(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	oldID := "old-correlation-12345"
	newID := "new-correlation-12345"

	// Seed an old trace older than cutoff (1 hour)
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Timestamp: time.Now().Add(-2 * time.Hour)},
	}
	traceMutex.Unlock()

	// Storing a new trace should trigger cleanup and remove oldID
	storeTrace(newID, TraceData{Timestamp: time.Now()})

	all := GetAllTraces()
	_, oldExists := all[oldID]
	assert.False(t, oldExists, "old traces should be cleaned up")
	_, newExists := all[newID]
	assert.True(t, newExists, "new trace should be present")
}

func TestGetTraces_EmptyForUnknownID(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	out := GetTraces("nope")
	assert.NotNil(t, out)
	assert.Len(t, out, 0)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	cid := "copy-test-123456"
	storeTrace(cid, TraceData{Path: "/a", Timestamp: time.Now()})
	storeTrace(cid, TraceData{Path: "/b", Timestamp: time.Now()})

	got := GetTraces(cid)
	require.Len(t, got, 2)
	got[0].Path = "/mutated"

	again := GetTraces(cid)
	assert.Equal(t, "/a", again[0].Path, "mutation of returned slice should not affect store")
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	storeTrace("a", TraceData{Path: "/a1", Timestamp: time.Now()})
	storeTrace("a", TraceData{Path: "/a2", Timestamp: time.Now()})
	storeTrace("b", TraceData{Path: "/b1", Timestamp: time.Now()})

	all := GetAllTraces()
	require.Len(t, all, 2)
	assert.Len(t, all["a"], 2)
	assert.Len(t, all["b"], 1)

	// Mutate returned copy
	all["a"][0].Path = "/mutated"
	all["b"] = append(all["b"], TraceData{Path: "/b2"})

	// Verify store unaffected
	again := GetAllTraces()
	assert.Equal(t, "/a1", again["a"][0].Path)
	assert.Len(t, again["b"], 1)
}

func TestResponseWriter_WriteHeader_SetsStatusCode(t *testing.T) {
	t.Cleanup(resetTraceStorage)

	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rec.Result().StatusCode)
}

func TestCorrelationIDMiddleware_UsesExistingHeaderAndStoresTrace(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	var capturedCtxID string
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				capturedCtxID = s
			}
		}
		_, _ = w.Write([]byte("ok"))
	})

	cid := "valid-ctx-abcdef1234"
	req := httptest.NewRequest(http.MethodGet, "/ctx", nil)
	req.Header.Set(CorrelationIDHeader, cid)
	rec := httptest.NewRecorder()

	CorrelationIDMiddleware(handler).ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	assert.Equal(t, "ok", string(body))
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	headerID := resp.Header.Get(CorrelationIDHeader)
	assert.Equal(t, cid, headerID, "middleware should propagate incoming correlation ID")
	assert.Equal(t, cid, capturedCtxID, "middleware should add correlation ID to context")

	traces := GetTraces(cid)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodGet, tr.Method)
	assert.Equal(t, "/ctx", tr.Path)
	assert.Equal(t, cid, tr.CorrelationID)
	assert.Equal(t, http.StatusOK, tr.Status)
	assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
}

func TestCorrelationIDMiddleware_GeneratesIDAndCapturesExplicitStatus(t *testing.T) {
	resetTraceStorage()
	t.Cleanup(resetTraceStorage)

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "bad", http.StatusTeapot)
	})

	req := httptest.NewRequest(http.MethodGet, "/brew", nil)
	rec := httptest.NewRecorder()

	CorrelationIDMiddleware(handler).ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()

	cid := resp.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, cid)
	assert.True(t, isValidCorrelationID(cid))

	traces := GetTraces(cid)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusTeapot, traces[0].Status)
	assert.Equal(t, "/brew", traces[0].Path)
}
