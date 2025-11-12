package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStore(t *testing.T) {
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
		{"valid-min-length", "abcdefghij", true}, // length 10
		{"valid-with-dash", "abc-12345-xyz", true},
		{"valid-with-underscore", "abc_12345_xyz", true},
		{"too-short", "short", false},
		{"too-long", string(make([]byte, 101)), false},
		{"invalid-chars", "abc$123", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestExtractOrGenerateCorrelationID_UsesExistingValidHeader(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	valid := "abc-12345-xyz"
	req.Header.Set(CorrelationIDHeader, valid)

	got := extractOrGenerateCorrelationID(req)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateCorrelationID_GeneratesWhenMissingOrInvalid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	got := extractOrGenerateCorrelationID(req)
	assert.NotEmpty(t, got)
	assert.True(t, isValidCorrelationID(got))

	req2 := httptest.NewRequest(http.MethodGet, "/", nil)
	req2.Header.Set(CorrelationIDHeader, "bad!") // invalid chars
	got2 := extractOrGenerateCorrelationID(req2)
	assert.NotEqual(t, "bad!", got2)
	assert.True(t, isValidCorrelationID(got2))
}

func TestExtractOrGenerateID_PublicWrapper(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(req)
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestGenerateCorrelationID_IsValid(t *testing.T) {
	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
	assert.Contains(t, id, "-go-")
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	w := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	w.WriteHeader(http.StatusCreated)
	assert.Equal(t, http.StatusCreated, w.statusCode)
	assert.Equal(t, http.StatusCreated, rr.Code)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_DefaultStatus(t *testing.T) {
	resetTraceStore(t)

	var handlerCtxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		handlerCtxID, _ = v.(string)
		_, _ = w.Write([]byte("ok")) // no WriteHeader => defaults to 200
	})

	mw := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/path", nil)

	mw.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, handlerCtxID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		tr := traces[0]
		assert.Equal(t, "go-parser", tr.Service)
		assert.Equal(t, http.StatusOK, tr.Status)
		assert.Equal(t, "/path", tr.Path)
		assert.Equal(t, http.MethodGet, tr.Method)
		assert.Equal(t, respID, tr.CorrelationID)
		assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_RespectsExistingID_TracksStatus(t *testing.T) {
	resetTraceStore(t)

	existing := "abcd-12345-xyz"
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		ctxID, _ := v.(string)
		assert.Equal(t, existing, ctxID)
		w.WriteHeader(http.StatusTeapot)
	})

	mw := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/tea", nil)
	req.Header.Set(CorrelationIDHeader, existing)

	mw.ServeHTTP(rr, req)

	assert.Equal(t, existing, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(existing)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusTeapot, traces[0].Status)
		assert.Equal(t, "/tea", traces[0].Path)
	}
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStore(t)

	id := "abcdef-12345"
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusBadRequest)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusBadRequest, traces[0].Status)
		assert.Equal(t, "/track", traces[0].Path)
		assert.Equal(t, http.MethodPost, traces[0].Method)
	}
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraceStore(t)

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestStoreTrace_AppendsAndGetTraces(t *testing.T) {
	resetTraceStore(t)

	id := "abcde-12345"
	t1 := TraceData{CorrelationID: id, Timestamp: time.Now(), Status: 200}
	t2 := TraceData{CorrelationID: id, Timestamp: time.Now().Add(10 * time.Millisecond), Status: 201}

	storeTrace(id, t1)
	storeTrace(id, t2)

	traces := GetTraces(id)
	assert.Len(t, traces, 2)
	assert.Equal(t, 200, traces[0].Status)
	assert.Equal(t, 201, traces[1].Status)
}

func TestCleanupOldTraces_RemovesOnlyOldEntries(t *testing.T) {
	resetTraceStore(t)

	oldID := "old-123456"
	newID := "new-123456"

	oldTrace := TraceData{CorrelationID: oldID, Timestamp: time.Now().Add(-2 * time.Hour)}
	newTrace := TraceData{CorrelationID: newID, Timestamp: time.Now().Add(-10 * time.Minute)}

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{oldTrace}
	traceStorage[newID] = []TraceData{newTrace}
	cleanupOldTraces()
	traceMutex.Unlock()

	all := GetAllTraces()
	_, hasOld := all[oldID]
	_, hasNew := all[newID]
	assert.False(t, hasOld)
	assert.True(t, hasNew)
}

func TestGetTraces_ReturnsEmptySliceForUnknownID(t *testing.T) {
	resetTraceStore(t)

	unknown := GetTraces("does-not-exist")
	assert.NotNil(t, unknown)
	assert.Len(t, unknown, 0)
}

func TestGetAllTraces_ReturnsCopyNotAlias(t *testing.T) {
	resetTraceStore(t)

	id := "copy-123456"
	td := TraceData{CorrelationID: id, Timestamp: time.Now(), Status: 200}
	storeTrace(id, td)

	all := GetAllTraces()
	assert.Len(t, all, 1)
	ret := all[id]
	assert.Len(t, ret, 1)

	// Mutate returned data; internal store should remain unchanged
	ret[0].Status = 999
	ret = append(ret, TraceData{CorrelationID: id, Status: 201})
	all[id] = ret

	orig := GetTraces(id)
	assert.Len(t, orig, 1)
	assert.Equal(t, 200, orig[0].Status)
}

func TestCorrelationIDMiddleware_ContextValueIsString(t *testing.T) {
	resetTraceStore(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		_, ok := v.(string)
		assert.True(t, ok)
	})

	mw := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/", nil)

	mw.ServeHTTP(rr, req)
}

func TestCorrelationIDMiddleware_InvalidIncomingHeader_GeneratesNewIDAndStoresUnderNew(t *testing.T) {
	resetTraceStore(t)

	invalid := "bad!"
	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		ctxID, _ = v.(string)
	})

	mw := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, invalid)

	mw.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.NotEqual(t, invalid, respID)
	assert.Equal(t, respID, ctxID)

	// Ensure trace stored under new ID, not the invalid one
	tracesNew := GetTraces(respID)
	assert.Len(t, tracesNew, 1)
	tracesInvalid := GetTraces(invalid)
	assert.Len(t, tracesInvalid, 0)
}

func TestCorrelationIDMiddleware_PropagatesRequestAndResponse(t *testing.T) {
	resetTraceStore(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify the value can be retrieved downstream using the known key
		val := r.Context().Value(CorrelationIDKey)
		_, ok := val.(string)
		assert.True(t, ok)
		w.WriteHeader(http.StatusAccepted)
	})

	mw := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/prop", nil)

	mw.ServeHTTP(rr, req)

	assert.NotEmpty(t, rr.Header().Get(CorrelationIDHeader))
	assert.Equal(t, http.StatusAccepted, rr.Code)

	id := rr.Header().Get(CorrelationIDHeader)
	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
	}
}

func TestTrackRequest_UsesRequestHeaderOnly(t *testing.T) {
	resetTraceStore(t)

	// Set context with a correlation ID that differs from header to ensure TrackRequest uses header
	req := httptest.NewRequest(http.MethodGet, "/track/header-only", nil)
	headerID := "header-123456"
	ctxID := "ctx-123456"
	req.Header.Set(CorrelationIDHeader, headerID)
	req = req.WithContext(context.WithValue(req.Context(), CorrelationIDKey, ctxID))

	TrackRequest(req, http.StatusOK)

	tracesHeader := GetTraces(headerID)
	tracesCtx := GetTraces(ctxID)
	assert.Len(t, tracesHeader, 1)
	assert.Len(t, tracesCtx, 0)
}
