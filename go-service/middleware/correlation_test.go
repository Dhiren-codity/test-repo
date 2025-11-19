package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraces(t *testing.T) {
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
		{"valid with dash and underscore", "abc_123-XYZ", true},
		{"too short", "short", false},
		{"too long", string(make([]byte, 101)), false},
		{"invalid char", "invalid#id-12345", false},
		{"valid long", "valid-12345-id", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_ValidFormat(t *testing.T) {
	id := generateCorrelationID()
	assert.True(t, isValidCorrelationID(id))
	assert.Regexp(t, regexp.MustCompile(`^\d+-go-\d+$`), id)
}

func TestExtractOrGenerateID_UsesExistingWhenValid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	existing := "valid-12345"
	req.Header.Set(CorrelationIDHeader, existing)

	got := ExtractOrGenerateID(req)
	assert.Equal(t, existing, got)
}

func TestExtractOrGenerateID_GeneratesWhenInvalidOrMissing(t *testing.T) {
	// Invalid present
	reqInvalid := httptest.NewRequest(http.MethodGet, "/", nil)
	reqInvalid.Header.Set(CorrelationIDHeader, "short")
	gotInvalid := ExtractOrGenerateID(reqInvalid)
	assert.NotEqual(t, "short", gotInvalid)
	assert.True(t, isValidCorrelationID(gotInvalid))

	// Missing
	reqMissing := httptest.NewRequest(http.MethodGet, "/", nil)
	gotMissing := ExtractOrGenerateID(reqMissing)
	assert.NotEmpty(t, gotMissing)
	assert.True(t, isValidCorrelationID(gotMissing))
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestTrackRequest_WithHeader_StoresTrace(t *testing.T) {
	resetTraces(t)

	id := "req-abc-12345"
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, "go-parser", traces[0].Service)
		assert.Equal(t, http.MethodPost, traces[0].Method)
		assert.Equal(t, "/track", traces[0].Path)
		assert.Equal(t, id, traces[0].CorrelationID)
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
	}
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraces(t)

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	traces := GetTraces("anything")
	assert.Len(t, traces, 0)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces(t)

	id := "copy-id-12345"
	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	}
	storeTrace(id, td)

	tr1 := GetTraces(id)
	assert.Len(t, tr1, 1)
	tr1[0].Status = http.StatusInternalServerError

	tr2 := GetTraces(id)
	assert.Len(t, tr2, 1)
	assert.Equal(t, http.StatusOK, tr2[0].Status, "internal storage should not be affected by modifying returned slice")
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces(t)

	id1 := "id-one-12345"
	id2 := "id-two-12345"
	td1 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: time.Now(), CorrelationID: id1, Status: http.StatusOK}
	td2 := TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/b", Timestamp: time.Now(), CorrelationID: id2, Status: http.StatusCreated}

	storeTrace(id1, td1)
	storeTrace(id2, td2)

	all := GetAllTraces()
	assert.Len(t, all, 2)

	// mutate the returned copy
	all[id1][0].Status = http.StatusInternalServerError
	all[id2][0].Path = "/mutated"

	// verify original unaffected
	tr1 := GetTraces(id1)
	tr2 := GetTraces(id2)
	assert.Equal(t, http.StatusOK, tr1[0].Status)
	assert.Equal(t, "/b", tr2[0].Path)
}

func TestCleanupOldTraces_RemovesExpiredOnStore(t *testing.T) {
	resetTraces(t)

	oldID := "old-id-12345"
	newID := "new-id-12345"

	// Insert an old trace directly
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{
			Service:       "go-parser",
			Method:        http.MethodGet,
			Path:          "/old",
			Timestamp:     time.Now().Add(-2 * time.Hour),
			CorrelationID: oldID,
			Status:        http.StatusOK,
		},
	}
	traceMutex.Unlock()

	// Storing a new trace should trigger cleanup of old one
	storeTrace(newID, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/new",
		Timestamp:     time.Now(),
		CorrelationID: newID,
		Status:        http.StatusOK,
	})

	assert.Len(t, GetTraces(oldID), 0)
	assert.Len(t, GetTraces(newID), 1)
}

func TestCorrelationIDMiddleware_UsesExistingIDAndStoresTrace(t *testing.T) {
	resetTraces(t)

	existing := "existing-id-12345"
	var ctxID string
	var ctxHas bool

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		id, ok := v.(string)
		ctxID = id
		ctxHas = ok
		w.WriteHeader(http.StatusCreated)
	})

	handler := CorrelationIDMiddleware(next)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mw", nil)
	req.Header.Set(CorrelationIDHeader, existing)

	handler.ServeHTTP(rr, req)

	resp := rr.Result()
	assert.Equal(t, http.StatusCreated, resp.StatusCode)
	assert.Equal(t, existing, resp.Header.Get(CorrelationIDHeader))
	assert.True(t, ctxHas)
	assert.Equal(t, existing, ctxID)

	traces := GetTraces(existing)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, "go-parser", traces[0].Service)
		assert.Equal(t, http.MethodGet, traces[0].Method)
		assert.Equal(t, "/mw", traces[0].Path)
		assert.Equal(t, existing, traces[0].CorrelationID)
		assert.Equal(t, http.StatusCreated, traces[0].Status)
		assert.GreaterOrEqual(t, traces[0].DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_GeneratesWhenNoHeader(t *testing.T) {
	resetTraces(t)

	var seenCtxID string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			seenCtxID = v
		}
		w.WriteHeader(http.StatusAccepted)
	})

	handler := CorrelationIDMiddleware(next)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/auto", nil)

	handler.ServeHTTP(rr, req)

	resp := rr.Result()
	respID := resp.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.True(t, isValidCorrelationID(respID))
	assert.Equal(t, respID, seenCtxID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
		assert.Equal(t, http.MethodPost, traces[0].Method)
		assert.Equal(t, "/auto", traces[0].Path)
	}
}

func TestCorrelationIDMiddleware_IgnoresInvalidExistingHeader(t *testing.T) {
	resetTraces(t)

	invalid := "short" // invalid by length
	var ctxID string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			ctxID = v
		}
		w.WriteHeader(http.StatusOK)
	})

	handler := CorrelationIDMiddleware(next)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, invalid)

	handler.ServeHTTP(rr, req)

	resp := rr.Result()
	respID := resp.Header.Get(CorrelationIDHeader)
	assert.NotEqual(t, invalid, respID)
	assert.True(t, isValidCorrelationID(respID))
	assert.Equal(t, respID, ctxID)

	// No traces should be stored under the invalid header value
	assert.Len(t, GetTraces(invalid), 0)
	// But should be stored under the generated one
	assert.Len(t, GetTraces(respID), 1)
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraces(t)

	var ctxID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			ctxID = v
		}
		_, _ = w.Write([]byte("ok")) // no explicit WriteHeader
	})

	handler := CorrelationIDMiddleware(next)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/default-status", nil)

	handler.ServeHTTP(rr, req)

	resp := rr.Result()
	id := resp.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, id)
	assert.Equal(t, id, ctxID)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusOK, traces[0].Status)
	}
}
