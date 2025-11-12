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

func resetTraces(t *testing.T) {
	t.Helper()
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"min length valid", "abcdefghij", true},
		{"valid with underscore and dash", "abc_123-XYZ", true},
		{"max length 100", strings.Repeat("a", 100), true},
		{"too short", "short", false},
		{"too long 101", strings.Repeat("b", 101), false},
		{"contains space", "invalid id", false},
		{"contains slash", "bad/slash", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_ValidAndUnique(t *testing.T) {
	id1 := generateCorrelationID()
	id2 := generateCorrelationID()
	require.NotEmpty(t, id1)
	require.NotEmpty(t, id2)
	assert.NotEqual(t, id1, id2)
	assert.True(t, isValidCorrelationID(id1))
	assert.True(t, isValidCorrelationID(id2))
}

func TestExtractOrGenerateID_UsesExistingValid(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	existing := "valid-ABC_1234567890"
	r.Header.Set(CorrelationIDHeader, existing)

	got := ExtractOrGenerateID(r)
	assert.Equal(t, existing, got)
}

func TestExtractOrGenerateID_GeneratesWhenInvalidOrMissing(t *testing.T) {
	// Missing header
	r1 := httptest.NewRequest(http.MethodGet, "/", nil)
	id1 := ExtractOrGenerateID(r1)
	assert.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// Invalid header
	r2 := httptest.NewRequest(http.MethodGet, "/", nil)
	r2.Header.Set(CorrelationIDHeader, "bad id")
	id2 := ExtractOrGenerateID(r2)
	assert.NotEmpty(t, id2)
	assert.True(t, isValidCorrelationID(id2))
	assert.NotEqual(t, "bad id", id2)
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace_Default200(t *testing.T) {
	resetTraces(t)

	var capturedID string
	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			capturedID = v
		}
		// No WriteHeader explicitly; default 200 should be recorded by wrapper
		io.WriteString(w, "ok")
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test-path", nil)
	handler.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)
	assert.Equal(t, respID, capturedID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)

	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodGet, tr.Method)
	assert.Equal(t, "/test-path", tr.Path)
	assert.Equal(t, respID, tr.CorrelationID)
	assert.Equal(t, http.StatusOK, tr.Status)
	assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
}

func TestCorrelationIDMiddleware_UsesExistingValidHeader(t *testing.T) {
	resetTraces(t)

	existing := "existing-ABC_1234567"
	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, "created")
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/with-existing", nil)
	req.Header.Set(CorrelationIDHeader, existing)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, existing, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(existing)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusCreated, traces[0].Status)
}

func TestCorrelationIDMiddleware_InvalidHeader_GeneratesNew(t *testing.T) {
	resetTraces(t)

	invalid := "bad id!"
	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, "ok")
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/invalid-header", nil)
	req.Header.Set(CorrelationIDHeader, invalid)
	handler.ServeHTTP(rr, req)

	newID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, newID)
	assert.NotEqual(t, invalid, newID)
	assert.True(t, isValidCorrelationID(newID))

	// No traces stored under invalid
	assert.Len(t, GetTraces(invalid), 0)
	// Trace stored under new
	assert.Len(t, GetTraces(newID), 1)
}

func TestCorrelationIDMiddleware_RecordsDurationAndStatus(t *testing.T) {
	resetTraces(t)

	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(12 * time.Millisecond)
		w.WriteHeader(http.StatusTeapot)
		io.WriteString(w, "body")
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/slow", nil)
	handler.ServeHTTP(rr, req)

	id := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, id)

	traces := GetTraces(id)
	require.Len(t, traces, 1)

	tr := traces[0]
	assert.Equal(t, http.StatusTeapot, tr.Status)
	assert.GreaterOrEqual(t, tr.DurationMS, float64(10))
}

func TestTrackRequest_NoHeader_NoTrace(t *testing.T) {
	resetTraces(t)

	req := httptest.NewRequest(http.MethodPost, "/track/noheader", nil)
	TrackRequest(req, http.StatusAccepted)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestTrackRequest_WithHeader_AddsTrace(t *testing.T) {
	resetTraces(t)

	id := "track-ABC_1234567890"
	req := httptest.NewRequest(http.MethodPatch, "/track/withheader", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusAccepted)

	got := GetTraces(id)
	require.Len(t, got, 1)

	tr := got[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodPatch, tr.Method)
	assert.Equal(t, "/track/withheader", tr.Path)
	assert.Equal(t, id, tr.CorrelationID)
	assert.Equal(t, http.StatusAccepted, tr.Status)
}

func TestResponseWriter_WriteHeader_RecordsStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces(t)

	id := "copy-1234567890"
	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/a",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	}
	storeTrace(id, td)

	s1 := GetTraces(id)
	require.Len(t, s1, 1)
	s1[0].Method = "CHANGED"

	s2 := GetTraces(id)
	require.Len(t, s2, 1)
	assert.Equal(t, http.MethodGet, s2[0].Method)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces(t)

	id1 := "id1-1234567890"
	id2 := "id2-1234567890"
	storeTrace(id1, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/x", Timestamp: time.Now(), CorrelationID: id1})
	storeTrace(id2, TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/y", Timestamp: time.Now(), CorrelationID: id2})

	all := GetAllTraces()
	require.Len(t, all, 2)

	// mutate returned copy
	for k, v := range all {
		if len(v) > 0 {
			v[0].Method = "CHANGED"
		}
		all[k] = nil
	}

	again := GetAllTraces()
	require.Len(t, again, 2)
	for _, v := range again {
		require.NotEmpty(t, v)
		assert.NotEqual(t, "CHANGED", v[0].Method)
	}
}

func TestCleanupOldTraces_RemovesExpired(t *testing.T) {
	resetTraces(t)

	oldID := "old-1234567890"
	newID := "new-1234567890"

	// Insert an old trace (>1h ago)
	storeTrace(oldID, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: oldID,
		Status:        http.StatusOK,
	})

	// Insert a new trace (this triggers cleanup)
	storeTrace(newID, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/new",
		Timestamp:     time.Now(),
		CorrelationID: newID,
		Status:        http.StatusOK,
	})

	// Ensure old traces were cleaned
	assert.Empty(t, GetTraces(oldID))
	assert.NotEmpty(t, GetTraces(newID))
}
