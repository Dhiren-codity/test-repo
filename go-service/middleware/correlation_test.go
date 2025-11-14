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
		{name: "valid length 10", id: "abcdefghij", want: true},
		{name: "valid with hyphen", id: "abcde-12345", want: true},
		{name: "valid with underscore", id: "abc_def_12345", want: true},
		{name: "invalid too short", id: "short", want: false},
		{name: "invalid too long", id: strings.Repeat("a", 101), want: false},
		{name: "invalid char dollar", id: "abc$def", want: false},
		{name: "invalid space", id: "abc def", want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestExtractOrGenerateCorrelationID_ValidHeader(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set(CorrelationIDHeader, "valid-12345")
	got := extractOrGenerateCorrelationID(req)
	assert.Equal(t, "valid-12345", got)
}

func TestExtractOrGenerateCorrelationID_InvalidOrMissing(t *testing.T) {
	t.Run("missing header generates", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/x", nil)
		got := extractOrGenerateCorrelationID(req)
		assert.NotEmpty(t, got)
		assert.True(t, isValidCorrelationID(got))
	})

	t.Run("invalid header generates new", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/x", nil)
		req.Header.Set(CorrelationIDHeader, "short")
		got := extractOrGenerateCorrelationID(req)
		assert.NotEqual(t, "short", got)
		assert.True(t, isValidCorrelationID(got))
	})
}

func TestGenerateCorrelationID_IsValid(t *testing.T) {
	id1 := generateCorrelationID()
	assert.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// generate another and ensure valid; avoid assuming uniqueness to prevent flakiness
	time.Sleep(1 * time.Millisecond)
	id2 := generateCorrelationID()
	assert.NotEmpty(t, id2)
	assert.True(t, isValidCorrelationID(id2))
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestCorrelationIDMiddleware_UsesExistingID_StoresTraceAndContext(t *testing.T) {
	resetTraceStorage(t)

	const cid = "valid-12345"

	var ctxID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		if s, ok := v.(string); ok {
			ctxID = s
		}
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte("ok"))
	})

	handler := CorrelationIDMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	req.Header.Set(CorrelationIDHeader, cid)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	assert.Equal(t, cid, rr.Header().Get(CorrelationIDHeader))
	assert.Equal(t, cid, ctxID)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/path", td.Path)
		assert.Equal(t, cid, td.CorrelationID)
		assert.Equal(t, http.StatusAccepted, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_GeneratesID_WhenMissing(t *testing.T) {
	resetTraceStorage(t)

	var capturedID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		if s, ok := v.(string); ok {
			capturedID = s
		}
		_, _ = w.Write([]byte("ok"))
	})

	handler := CorrelationIDMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/missing", nil)
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	assert.NotEmpty(t, capturedID)
	assert.True(t, isValidCorrelationID(capturedID))
	assert.Equal(t, capturedID, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(capturedID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusOK, td.Status)
	}
}

func TestCorrelationIDMiddleware_GeneratesID_WhenInvalidProvided(t *testing.T) {
	resetTraceStorage(t)

	var capturedID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		if s, ok := v.(string); ok {
			capturedID = s
		}
		w.WriteHeader(http.StatusCreated)
	})

	handler := CorrelationIDMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, "short")
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	assert.NotEqual(t, "short", capturedID)
	assert.True(t, isValidCorrelationID(capturedID))
	assert.Equal(t, capturedID, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(capturedID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusCreated, td.Status)
	}
}

func TestTrackRequest_WithHeader_StoresTrace(t *testing.T) {
	resetTraceStorage(t)

	const cid = "valid-12345"
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusInternalServerError)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, "/track", td.Path)
		assert.Equal(t, cid, td.CorrelationID)
		assert.Equal(t, http.StatusInternalServerError, td.Status)
	}
}

func TestTrackRequest_WithoutHeader_NoTrace(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestStoreTrace_GetTraces_And_GetAllTraces_CopyIsolation(t *testing.T) {
	resetTraceStorage(t)

	t1 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/p1", Timestamp: time.Now(), CorrelationID: "id1", Status: 200}
	t2 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/p2", Timestamp: time.Now(), CorrelationID: "id1", Status: 201}
	t3 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/p3", Timestamp: time.Now(), CorrelationID: "id2", Status: 202}

	storeTrace("id1", t1)
	storeTrace("id1", t2)
	storeTrace("id2", t3)

	got := GetTraces("id1")
	assert.Len(t, got, 2)
	assert.Equal(t, "/p1", got[0].Path)
	assert.Equal(t, "/p2", got[1].Path)

	// Mutate returned slice and ensure original store is unaffected
	got[0].Path = "mutated"
	gotAgain := GetTraces("id1")
	assert.Equal(t, "/p1", gotAgain[0].Path)

	all := GetAllTraces()
	assert.Len(t, all, 2)
	assert.Len(t, all["id1"], 2)
	assert.Len(t, all["id2"], 1)

	// Mutate returned map/slice copy and ensure store unchanged
	all["id1"][0].Path = "changed"
	gotAfter := GetTraces("id1")
	assert.Equal(t, "/p1", gotAfter[0].Path)
}

func TestCleanupOldTraces_RemovesOld(t *testing.T) {
	resetTraceStorage(t)

	// Seed an old trace bucket
	traceMutex.Lock()
	traceStorage["old-id"] = []TraceData{
		{Service: "go-parser", Method: http.MethodGet, Path: "/old", Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: "old-id", Status: 200},
	}
	traceMutex.Unlock()

	// Trigger cleanup by storing a new trace
	storeTrace("new-id", TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/new", Timestamp: time.Now(), CorrelationID: "new-id", Status: 200})

	old := GetTraces("old-id")
	assert.Len(t, old, 0)

	new := GetTraces("new-id")
	assert.Len(t, new, 1)
}
