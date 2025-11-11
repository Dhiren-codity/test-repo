package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraces() {
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
		{"exactly 10", "abcde-1234", true},
		{"exactly 100", func() string {
			s := make([]rune, 100)
			for i := range s {
				s[i] = 'a'
			}
			return string(s)
		}(), true},
		{"too long", func() string {
			s := make([]rune, 101)
			for i := range s {
				s[i] = 'a'
			}
			return string(s)
		}(), false},
		{"invalid chars", "abc/12345", false},
		{"valid with hyphen and underscore", "valid-id_12345", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_Valid(t *testing.T) {
	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
	assert.True(t, validIDRegex.MatchString(id))
	assert.GreaterOrEqual(t, len(id), 10)
	assert.LessOrEqual(t, len(id), 100)
}

func TestExtractOrGenerateCorrelationID(t *testing.T) {
	// Valid incoming header
	req1 := httptest.NewRequest(http.MethodGet, "http://example.com/a", nil)
	req1.Header.Set(CorrelationIDHeader, "valid-abc_12345")
	got1 := extractOrGenerateCorrelationID(req1)
	assert.Equal(t, "valid-abc_12345", got1)

	// Missing header -> generate
	req2 := httptest.NewRequest(http.MethodGet, "http://example.com/b", nil)
	got2 := extractOrGenerateCorrelationID(req2)
	assert.NotEmpty(t, got2)
	assert.True(t, isValidCorrelationID(got2))

	// Invalid header -> generate new
	req3 := httptest.NewRequest(http.MethodGet, "http://example.com/c", nil)
	req3.Header.Set(CorrelationIDHeader, "bad id")
	got3 := extractOrGenerateCorrelationID(req3)
	assert.NotEqual(t, "bad id", got3)
	assert.True(t, isValidCorrelationID(got3))
}

func TestExtractOrGenerateID_Exported(t *testing.T) {
	req1 := httptest.NewRequest(http.MethodGet, "/", nil)
	req1.Header.Set(CorrelationIDHeader, "incoming-12345")
	got1 := ExtractOrGenerateID(req1)
	assert.Equal(t, "incoming-12345", got1)

	req2 := httptest.NewRequest(http.MethodGet, "/", nil)
	got2 := ExtractOrGenerateID(req2)
	assert.NotEmpty(t, got2)
	assert.True(t, isValidCorrelationID(got2))
}

func TestCorrelationIDMiddleware_SetsHeader_StoresTrace_Implicit200(t *testing.T) {
	resetTraces()

	var idInCtx string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				idInCtx = s
			}
		}
		_, _ = w.Write([]byte("ok"))
	})

	srv := CorrelationIDMiddleware(h)
	req := httptest.NewRequest(http.MethodGet, "http://example.com/path", nil)
	rr := httptest.NewRecorder()

	srv.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, idInCtx)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/path", td.Path)
		assert.Equal(t, respID, td.CorrelationID)
		assert.Equal(t, http.StatusOK, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
		assert.False(t, td.Timestamp.IsZero())
	}
}

func TestCorrelationIDMiddleware_UsesIncomingValidID_AndCapturesStatus(t *testing.T) {
	resetTraces()

	incoming := "incoming-valid-12345"
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		assert.Equal(t, incoming, v)
		w.WriteHeader(http.StatusTeapot)
	})

	srv := CorrelationIDMiddleware(h)
	req := httptest.NewRequest(http.MethodPost, "http://example.com/resource", nil)
	req.Header.Set(CorrelationIDHeader, incoming)
	rr := httptest.NewRecorder()

	srv.ServeHTTP(rr, req)

	assert.Equal(t, incoming, rr.Header().Get(CorrelationIDHeader))
	traces := GetTraces(incoming)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusTeapot, td.Status)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, "/resource", td.Path)
	}
}

func TestCorrelationIDMiddleware_ReplacesInvalidIncomingID(t *testing.T) {
	resetTraces()

	var idInCtx string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			idInCtx, _ = v.(string)
		}
		w.WriteHeader(http.StatusCreated)
	})

	srv := CorrelationIDMiddleware(h)
	req := httptest.NewRequest(http.MethodGet, "http://example.com/replace", nil)
	req.Header.Set(CorrelationIDHeader, "bad id")
	rr := httptest.NewRecorder()

	srv.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEqual(t, "bad id", respID)
	assert.True(t, isValidCorrelationID(respID))
	assert.Equal(t, respID, idInCtx)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusCreated, traces[0].Status)
	}
}

func TestTrackRequest_Stores_WhenHeaderPresent(t *testing.T) {
	resetTraces()

	id := "track-12345-valid"
	req := httptest.NewRequest(http.MethodPut, "http://example.com/track", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, "go-parser", traces[0].Service)
		assert.Equal(t, http.MethodPut, traces[0].Method)
		assert.Equal(t, "/track", traces[0].Path)
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
		assert.Equal(t, id, traces[0].CorrelationID)
	}
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraces()

	req := httptest.NewRequest(http.MethodGet, "http://example.com/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces()

	id := "copy-test-12345"
	orig := TraceData{Service: "svc", Method: "GET", Path: "/x", Timestamp: time.Now(), CorrelationID: id, Status: 200}
	storeTrace(id, orig)

	got := GetTraces(id)
	assert.Len(t, got, 1)
	got[0].Service = "mutated"

	got2 := GetTraces(id)
	assert.Len(t, got2, 1)
	assert.Equal(t, "svc", got2[0].Service)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces()

	id1 := "id1-123456"
	id2 := "id2-123456"
	storeTrace(id1, TraceData{Service: "s1", Method: "GET", Path: "/a", Timestamp: time.Now(), CorrelationID: id1, Status: 200})
	storeTrace(id2, TraceData{Service: "s2", Method: "POST", Path: "/b", Timestamp: time.Now(), CorrelationID: id2, Status: 201})

	all := GetAllTraces()
	assert.Contains(t, all, id1)
	assert.Contains(t, all, id2)
	assert.Len(t, all[id1], 1)
	assert.Len(t, all[id2], 1)

	// mutate returned map and slices
	all[id1][0].Service = "mutated"
	all[id2] = nil

	// original store should be unaffected
	tr1 := GetTraces(id1)
	tr2 := GetTraces(id2)
	assert.Equal(t, "s1", tr1[0].Service)
	assert.Len(t, tr2, 1)
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraces()

	oldID := "old-123456"
	newID := "new-123456"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Service: "old", Method: "GET", Path: "/old", Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: oldID},
	}
	traceStorage[newID] = []TraceData{
		{Service: "new", Method: "GET", Path: "/new", Timestamp: time.Now(), CorrelationID: newID},
	}
	traceMutex.Unlock()

	// Trigger cleanup by storing any trace
	storeTrace("trigger-123", TraceData{Service: "t", Method: "GET", Path: "/t", Timestamp: time.Now(), CorrelationID: "trigger-123"})

	all := GetAllTraces()
	_, existsOld := all[oldID]
	_, existsNew := all[newID]
	assert.False(t, existsOld)
	assert.True(t, existsNew)
}

func TestResponseWriter_WriteHeader_SetsStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusCreated)

	assert.Equal(t, http.StatusCreated, rw.statusCode)
	assert.Equal(t, http.StatusCreated, rr.Code)
}
