package middleware

import (
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
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"too short", "short", false},
		{"too long", strings.Repeat("a", 101), false},
		{"invalid chars", "valid$%^&*", false},
		{"valid with hyphen and underscore", "abc-123_DEFx", true},
		{"boundary length 10", "abcdefghij", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID(t *testing.T) {
	id := generateCorrelationID()
	require.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id), "generated id should be valid")
	assert.Contains(t, id, "-go-")
}

func TestExtractOrGenerateID_WithValidHeader(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	headerID := "valid-abcde-12345"
	require.True(t, isValidCorrelationID(headerID))
	req.Header.Set(CorrelationIDHeader, headerID)

	id := ExtractOrGenerateID(req)
	assert.Equal(t, headerID, id)
}

func TestExtractOrGenerateID_WithInvalidHeader_GeneratesNew(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set(CorrelationIDHeader, "short")

	id := ExtractOrGenerateID(req)
	assert.NotEqual(t, "short", id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateID_NoHeader_GeneratesNew(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(req)
	require.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestTrackRequest_WithHeader_StoresTrace(t *testing.T) {
	resetTraceStorage()
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	headerID := "track-12345-ok"
	if len(headerID) < 10 {
		headerID = "track-12345-ok!!"
	}
	req.Header.Set(CorrelationIDHeader, headerID)

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces(headerID)
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.StatusCreated, td.Status)
	assert.Equal(t, req.Method, td.Method)
	assert.Equal(t, req.URL.Path, td.Path)
	assert.Equal(t, headerID, td.CorrelationID)
	assert.True(t, td.Timestamp.Before(time.Now().Add(1*time.Second)))
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraceStorage()
	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)

	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Equal(t, 0, len(all))
}

func TestCleanupOldTraces_RemovesOld(t *testing.T) {
	resetTraceStorage()
	oldID := "old-1234567890"
	newID := "new-1234567890"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{{Timestamp: time.Now().Add(-2 * time.Hour)}}
	traceStorage[newID] = []TraceData{{Timestamp: time.Now()}}
	traceMutex.Unlock()

	cleanupOldTraces()

	traceMutex.RLock()
	_, oldExists := traceStorage[oldID]
	_, newExists := traceStorage[newID]
	traceMutex.RUnlock()

	assert.False(t, oldExists, "old traces should be removed")
	assert.True(t, newExists, "new traces should remain")
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()
	id := "copy-1234567890"
	storeTrace(id, TraceData{Service: "go-parser", Timestamp: time.Now()})

	traces := GetTraces(id)
	require.Len(t, traces, 1)
	traces[0].Service = "mutated"

	again := GetTraces(id)
	require.Len(t, again, 1)
	assert.Equal(t, "go-parser", again[0].Service, "stored trace should not be affected by mutation")
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStorage()
	id1 := "id1-1234567890"
	id2 := "id2-1234567890"
	storeTrace(id1, TraceData{Status: 200, Timestamp: time.Now()})
	storeTrace(id2, TraceData{Status: 200, Timestamp: time.Now()})

	all := GetAllTraces()
	require.Len(t, all, 2)

	// Mutate returned map and inner slice
	delete(all, id1)
	all[id2][0].Status = 500

	// Ensure storage not affected
	tr1 := GetTraces(id1)
	require.Len(t, tr1, 1)
	assert.Equal(t, 200, tr1[0].Status)

	tr2 := GetTraces(id2)
	require.Len(t, tr2, 1)
	assert.Equal(t, 200, tr2[0].Status)

	all2 := GetAllTraces()
	assert.Contains(t, all2, id1)
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace_StatusCreated(t *testing.T) {
	resetTraceStorage()
	var capturedCtxID string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				capturedCtxID = s
			}
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("ok"))
	})

	req := httptest.NewRequest(http.MethodGet, "/abc", nil)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)
	require.NotEmpty(t, capturedCtxID)
	assert.Equal(t, respID, capturedCtxID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.StatusCreated, td.Status)
	assert.Equal(t, "/abc", td.Path)
	assert.Equal(t, respID, td.CorrelationID)
	assert.GreaterOrEqual(t, td.DurationMS, float64(0))
}

func TestCorrelationIDMiddleware_DefaultStatusOK_OnWrite(t *testing.T) {
	resetTraceStorage()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("hello"))
	})

	req := httptest.NewRequest(http.MethodGet, "/hello", nil)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestCorrelationIDMiddleware_UsesClientProvidedValidID(t *testing.T) {
	resetTraceStorage()

	clientID := "client-valid-12345"
	require.True(t, isValidCorrelationID(clientID))
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})

	req := httptest.NewRequest(http.MethodGet, "/provided", nil)
	req.Header.Set(CorrelationIDHeader, clientID)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.Equal(t, clientID, respID)

	traces := GetTraces(clientID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusNoContent, traces[0].Status)
	assert.Equal(t, "/provided", traces[0].Path)
}

func TestCorrelationIDMiddleware_ReplacesInvalidClientID(t *testing.T) {
	resetTraceStorage()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	})

	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, "short")
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)
	assert.NotEqual(t, "short", respID)
	assert.True(t, isValidCorrelationID(respID))

	// Ensure no traces under the invalid id
	trShort := GetTraces("short")
	assert.Len(t, trShort, 0)

	// Traces should exist under the generated id
	trNew := GetTraces(respID)
	require.Len(t, trNew, 1)
	assert.Equal(t, http.StatusAccepted, trNew[0].Status)
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}
