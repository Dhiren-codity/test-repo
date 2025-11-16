package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func clearTraces(t *testing.T) {
	traceMutex.Lock()
	for k := range traceStorage {
		delete(traceStorage, k)
	}
	traceMutex.Unlock()
}

func TestExtractOrGenerateID_ExistingValidHeader(t *testing.T) {
	clearTraces(t)

	r := httptest.NewRequest(http.MethodGet, "/x", nil)
	valid := "valid-12345-id"
	assert.True(t, isValidCorrelationID(valid))
	r.Header.Set(CorrelationIDHeader, valid)

	id := ExtractOrGenerateID(r)
	assert.Equal(t, valid, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateID_InvalidOrMissingHeaderGeneratesNew(t *testing.T) {
	clearTraces(t)

	// Missing header
	r1 := httptest.NewRequest(http.MethodGet, "/", nil)
	id1 := ExtractOrGenerateID(r1)
	assert.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// Invalid header (too short)
	r2 := httptest.NewRequest(http.MethodGet, "/", nil)
	r2.Header.Set(CorrelationIDHeader, "short")
	id2 := ExtractOrGenerateID(r2)
	assert.NotEqual(t, "short", id2)
	assert.True(t, isValidCorrelationID(id2))

	// Invalid header (contains space)
	r3 := httptest.NewRequest(http.MethodGet, "/", nil)
	r3.Header.Set(CorrelationIDHeader, "bad id with space")
	id3 := ExtractOrGenerateID(r3)
	assert.NotEqual(t, "bad id with space", id3)
	assert.True(t, isValidCorrelationID(id3))
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace(t *testing.T) {
	clearTraces(t)

	var capturedCtxID string
	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		val := r.Context().Value(CorrelationIDKey)
		if s, ok := val.(string); ok {
			capturedCtxID = s
		}
		w.WriteHeader(http.StatusTeapot)
		_, _ = w.Write([]byte("hello"))
	}))

	rr := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/check", nil)
	h.ServeHTTP(rr, r)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.True(t, isValidCorrelationID(respID))
	assert.Equal(t, respID, capturedCtxID)
	assert.Equal(t, http.StatusTeapot, rr.Code)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/check", td.Path)
		assert.Equal(t, respID, td.CorrelationID)
		assert.Equal(t, http.StatusTeapot, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_UsesExistingValidHeader(t *testing.T) {
	clearTraces(t)

	existing := "preexisting-12345"
	assert.True(t, isValidCorrelationID(existing))

	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// No-op
	}))
	rr := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	r.Header.Set(CorrelationIDHeader, existing)

	h.ServeHTTP(rr, r)
	assert.Equal(t, existing, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(existing)
	assert.Len(t, traces, 1)
}

func TestTrackRequest_WithHeader_StoresTrace(t *testing.T) {
	clearTraces(t)

	r := httptest.NewRequest(http.MethodPost, "/track", nil)
	id := "track-req-12345"
	r.Header.Set(CorrelationIDHeader, id)

	TrackRequest(r, http.StatusCreated)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, "/track", td.Path)
		assert.Equal(t, id, td.CorrelationID)
		assert.Equal(t, http.StatusCreated, td.Status)
	}
}

func TestTrackRequest_WithoutHeader_DoesNothing(t *testing.T) {
	clearTraces(t)

	r := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(r, http.StatusOK)

	// No known correlation ID; GetAllTraces should be empty
	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGenerateCorrelationID_IsValidAndUnique(t *testing.T) {
	clearTraces(t)

	id1 := generateCorrelationID()
	time.Sleep(2 * time.Millisecond)
	id2 := generateCorrelationID()

	assert.NotEmpty(t, id1)
	assert.NotEmpty(t, id2)
	assert.True(t, isValidCorrelationID(id1))
	assert.True(t, isValidCorrelationID(id2))
	assert.NotEqual(t, id1, id2)
}

func TestIsValidCorrelationID_Table(t *testing.T) {
	clearTraces(t)

	tests := []struct {
		id     string
		valid  bool
		reason string
	}{
		{"", false, "empty"},
		{"short", false, "too short"},
		{"with space 12345", false, "invalid character"},
		{"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab", false, "too long"},
		{"1234567890", true, "digits only"},
		{"abc-xyz_123", true, "alnum underscore hyphen"},
	}
	for _, tt := range tests {
		got := isValidCorrelationID(tt.id)
		assert.Equal(t, tt.valid, got, tt.reason)
	}
}

func TestStoreTraceAndGetTraces_AndCleanupOld(t *testing.T) {
	clearTraces(t)

	now := time.Now()
	idNew := "new-1234567"
	storeTrace(idNew, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/new",
		Timestamp:     now,
		CorrelationID: idNew,
		Status:        http.StatusOK,
	})
	got := GetTraces(idNew)
	if assert.Len(t, got, 1) {
		assert.Equal(t, "/new", got[0].Path)
	}

	// Old trace should be cleaned immediately within storeTrace call
	idOld := "old-1234567"
	storeTrace(idOld, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: idOld,
		Status:        http.StatusOK,
	})
	gotOld := GetTraces(idOld)
	assert.Len(t, gotOld, 0)
}

func TestCleanupOldTraces_RemovesWhenFirstTraceIsOldEvenIfLaterNew(t *testing.T) {
	clearTraces(t)

	id := "mix-1234567"
	old := time.Now().Add(-2 * time.Hour)
	newT := time.Now()

	traceMutex.Lock()
	traceStorage[id] = []TraceData{
		{Timestamp: old, CorrelationID: id, Path: "/old", Method: http.MethodGet, Service: "go-parser"},
		{Timestamp: newT, CorrelationID: id, Path: "/new", Method: http.MethodGet, Service: "go-parser"},
	}
	traceMutex.Unlock()

	cleanupOldTraces()

	got := GetTraces(id)
	assert.Len(t, got, 0)
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	clearTraces(t)

	id := "copy-1234567"
	storeTrace(id, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	})

	all := GetAllTraces()
	assert.Len(t, all, 1)
	// mutate the returned slice
	all[id] = append(all[id], TraceData{Path: "/mutated"})

	original := GetTraces(id)
	assert.Len(t, original, 1)
	assert.Equal(t, "/copy", original[0].Path)
}

func TestResponseWriter_WriteHeader_SetsStatus(t *testing.T) {
	clearTraces(t)

	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}
	rw.WriteHeader(http.StatusAccepted)

	assert.Equal(t, http.StatusAccepted, rw.statusCode)
	assert.Equal(t, http.StatusAccepted, rr.Code)
}

func TestCorrelationIDInContextWithinMiddleware(t *testing.T) {
	clearTraces(t)

	var got string
	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			got, _ = v.(string)
		}
		w.WriteHeader(http.StatusOK)
	}))
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	h.ServeHTTP(rr, req)

	assert.NotEmpty(t, got)
	assert.Equal(t, rr.Header().Get(CorrelationIDHeader), got)
}

func TestTrackRequest_DoesNotPanicWithoutContextID(t *testing.T) {
	clearTraces(t)

	req := httptest.NewRequest(http.MethodGet, "/noctx", nil)
	// ensure no correlation ID in header and context value is absent
	req = req.WithContext(context.WithValue(req.Context(), CorrelationIDKey, ""))

	// Should simply return without storing
	TrackRequest(req, http.StatusOK)
	all := GetAllTraces()
	assert.Len(t, all, 0)
}
