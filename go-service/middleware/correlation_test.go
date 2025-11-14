package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage(t *testing.T) {
	t.Helper()
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestIsValidCorrelationID_Table(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"valid_alnum", "abc1234567", true},
		{"valid_with_hyphen", "abc-1234567", true},
		{"valid_with_underscore", "abc_1234567", true},
		{"invalid_too_short", "short", false},
		{"invalid_too_long", strings.Repeat("a", 101), false},
		{"invalid_chars", "abc$defghij", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_FormatAndUniqueness(t *testing.T) {
	id1 := generateCorrelationID()
	time.Sleep(2 * time.Millisecond) // reduce collision probability
	id2 := generateCorrelationID()

	assert.NotEmpty(t, id1)
	assert.NotEmpty(t, id2)
	assert.Contains(t, id1, "-go-")
	assert.Contains(t, id2, "-go-")
	assert.NotEqual(t, id1, id2)
}

func TestExtractOrGenerateID_UsesExistingValid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	req.Header.Set(CorrelationIDHeader, "existing-12345")

	id := ExtractOrGenerateID(req)
	assert.Equal(t, "existing-12345", id)
}

func TestExtractOrGenerateID_GeneratesWhenMissing(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(req)
	assert.NotEmpty(t, id)
	assert.Contains(t, id, "-go-")
}

func TestExtractOrGenerateID_IgnoresInvalidAndGenerates(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set(CorrelationIDHeader, "bad id!")

	id := ExtractOrGenerateID(req)
	assert.NotEqual(t, "bad id!", id)
	assert.NotEmpty(t, id)
}

func TestStoreTraceAndGetTraces_CopySemantics(t *testing.T) {
	resetTraceStorage(t)

	id := "trace-123456"
	td := TraceData{
		Service:       "go-parser",
		Method:        "GET",
		Path:          "/a",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        200,
	}
	storeTrace(id, td)

	got := GetTraces(id)
	assert.Len(t, got, 1)
	assert.Equal(t, "/a", got[0].Path)

	// mutate returned slice; should not affect storage
	got[0].Path = "/mutated"
	got2 := GetTraces(id)
	assert.Equal(t, "/a", got2[0].Path)
}

func TestGetAllTraces_CopySemantics(t *testing.T) {
	resetTraceStorage(t)

	id1 := "id1-123456"
	id2 := "id2-123456"
	storeTrace(id1, TraceData{CorrelationID: id1, Path: "/p1", Timestamp: time.Now()})
	storeTrace(id2, TraceData{CorrelationID: id2, Path: "/p2", Timestamp: time.Now()})

	all := GetAllTraces()
	assert.Contains(t, all, id1)
	assert.Contains(t, all, id2)
	assert.Equal(t, "/p1", all[id1][0].Path)

	// mutate returned map content; underlying storage should remain unchanged
	all[id1][0].Path = "/changed"
	allAfter := GetAllTraces()
	assert.Equal(t, "/p1", allAfter[id1][0].Path)
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage(t)

	oldID := "old-123456"
	newID := "new-123456"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{{CorrelationID: oldID, Timestamp: time.Now().Add(-2 * time.Hour)}}
	traceStorage[newID] = []TraceData{{CorrelationID: newID, Timestamp: time.Now()}}
	traceMutex.Unlock()

	// Trigger cleanup via storeTrace which holds the lock and invokes cleanupOldTraces
	storeTrace("trigger-123456", TraceData{CorrelationID: "trigger-123456", Timestamp: time.Now()})

	traceMutex.RLock()
	_, oldExists := traceStorage[oldID]
	_, newExists := traceStorage[newID]
	traceMutex.RUnlock()

	assert.False(t, oldExists, "old traces should be removed")
	assert.True(t, newExists, "new traces should remain")
}

func TestTrackRequest_WithHeaderStoresTrace(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	cid := "existing-123456"
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusTeapot)

	traces := GetTraces(cid)
	assert.Len(t, traces, 1)
	assert.Equal(t, "go-parser", traces[0].Service)
	assert.Equal(t, http.MethodPost, traces[0].Method)
	assert.Equal(t, "/track", traces[0].Path)
	assert.Equal(t, http.StatusTeapot, traces[0].Status)
}

func TestTrackRequest_NoHeaderDoesNothing(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/no", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	wrapped := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	wrapped.WriteHeader(http.StatusConflict)

	assert.Equal(t, http.StatusConflict, wrapped.statusCode)
	assert.Equal(t, http.StatusConflict, rr.Code)
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace(t *testing.T) {
	resetTraceStorage(t)

	var gotCtxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				gotCtxID = s
			}
		}
		w.WriteHeader(http.StatusAccepted)
	})

	req := httptest.NewRequest(http.MethodGet, "/mw", nil)
	rr := httptest.NewRecorder()

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()

	respID := res.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, gotCtxID)

	traces := GetTraces(respID)
	assert.Len(t, traces, 1)
	assert.Equal(t, http.StatusAccepted, traces[0].Status)
	assert.Equal(t, "/mw", traces[0].Path)
	assert.Equal(t, http.MethodGet, traces[0].Method)
	assert.True(t, traces[0].DurationMS >= 0)
}

func TestCorrelationIDMiddleware_UsesExistingHeader(t *testing.T) {
	resetTraceStorage(t)

	existing := "existing-abcdef"
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	})

	req := httptest.NewRequest(http.MethodGet, "/exists", nil)
	req.Header.Set(CorrelationIDHeader, existing)
	rr := httptest.NewRecorder()

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()

	assert.Equal(t, existing, res.Header.Get(CorrelationIDHeader))

	all := GetAllTraces()
	assert.Len(t, all, 1)
	traces := GetTraces(existing)
	assert.Len(t, traces, 1)
	assert.Equal(t, http.StatusCreated, traces[0].Status)
	assert.Equal(t, "/exists", traces[0].Path)
}

func TestMiddleware_DefaultStatusWhenHandlerWritesNothing(t *testing.T) {
	resetTraceStorage(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// no write, no header
	})

	req := httptest.NewRequest(http.MethodGet, "/no-write", nil)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()

	id := res.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, id)

	traces := GetTraces(id)
	assert.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}
