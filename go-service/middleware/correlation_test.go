package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetTraces(t *testing.T) {
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
	t.Cleanup(func() {
		traceMutex.Lock()
		traceStorage = make(map[string][]TraceData)
		traceMutex.Unlock()
	})
}

func TestExtractOrGenerateID_UsesValidHeader(t *testing.T) {
	resetTraces(t)

	r := httptest.NewRequest(http.MethodGet, "/", nil)
	valid := "abcde-12345-ABCDE_67890"
	require.True(t, isValidCorrelationID(valid))
	r.Header.Set(CorrelationIDHeader, valid)

	got := ExtractOrGenerateID(r)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateID_GeneratesWhenMissingOrInvalid(t *testing.T) {
	resetTraces(t)

	// Missing header
	r1 := httptest.NewRequest(http.MethodGet, "/", nil)
	id1 := ExtractOrGenerateID(r1)
	assert.NotEmpty(t, id1)
	assert.Contains(t, id1, "-go-")

	// Invalid header should be ignored
	r2 := httptest.NewRequest(http.MethodGet, "/", nil)
	r2.Header.Set(CorrelationIDHeader, "invalid id!") // contains space and exclamation
	id2 := ExtractOrGenerateID(r2)
	assert.NotEmpty(t, id2)
	assert.NotEqual(t, "invalid id!", id2)
	assert.Contains(t, id2, "-go-")
}

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"too short", "short", false},
		{"min length valid", "abcdefghij", true}, // 10
		{"max length valid", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", true}, // 100 'a's
		{"too long", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false},       // 101
		{"invalid chars", "abc/def", false},
		{"valid hyphen underscore", "abc_def-123", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestResponseWriter_WriteHeaderTracksStatus(t *testing.T) {
	resetTraces(t)

	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace(t *testing.T) {
	resetTraces(t)

	var ctxID string
	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Grab correlation from context and make sure header reflects it
		val := r.Context().Value(CorrelationIDKey)
		var ok bool
		ctxID, ok = val.(string)
		require.True(t, ok)
		assert.Equal(t, ctxID, w.Header().Get(CorrelationIDHeader))
		// return a custom status
		w.WriteHeader(http.StatusAccepted)
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test/path", nil)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusAccepted, rr.Code)
	headerID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, headerID)
	assert.Equal(t, headerID, ctxID)

	// Ensure a trace was stored for that ID
	traces := GetTraces(headerID)
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodGet, td.Method)
	assert.Equal(t, "/test/path", td.Path)
	assert.Equal(t, headerID, td.CorrelationID)
	assert.Equal(t, http.StatusAccepted, td.Status)
	assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	assert.WithinDuration(t, time.Now(), td.Timestamp, time.Second)
}

func TestCorrelationIDMiddleware_DefaultsStatusTo200WhenNoWriteHeader(t *testing.T) {
	resetTraces(t)

	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok")) // no explicit WriteHeader
	}))

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/no/writeheader", nil)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	headerID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, headerID)

	traces := GetTraces(headerID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestTrackRequest_StoresTraceWhenHeaderPresent(t *testing.T) {
	resetTraces(t)

	r := httptest.NewRequest(http.MethodPost, "/track/me", nil)
	r.Header.Set(CorrelationIDHeader, "trace-123456789") // valid id (>=10)

	TrackRequest(r, http.StatusCreated)

	traces := GetTraces("trace-123456789")
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodPost, td.Method)
	assert.Equal(t, "/track/me", td.Path)
	assert.Equal(t, "trace-123456789", td.CorrelationID)
	assert.Equal(t, http.StatusCreated, td.Status)
	assert.WithinDuration(t, time.Now(), td.Timestamp, time.Second)
}

func TestTrackRequest_NoHeaderDoesNothing(t *testing.T) {
	resetTraces(t)

	r := httptest.NewRequest(http.MethodGet, "/no/header", nil)
	TrackRequest(r, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces(t)

	id := "copy-1234567890"
	now := time.Now()
	storeTrace(id, TraceData{CorrelationID: id, Method: "GET", Path: "/a", Timestamp: now})

	got := GetTraces(id)
	require.Len(t, got, 1)
	// mutate the returned slice
	got[0].Method = "MUTATED"

	got2 := GetTraces(id)
	require.Len(t, got2, 1)
	assert.Equal(t, "GET", got2[0].Method)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces(t)

	id1 := "id1-1234567890"
	id2 := "id2-1234567890"
	storeTrace(id1, TraceData{CorrelationID: id1, Method: "GET", Path: "/a", Timestamp: time.Now()})
	storeTrace(id2, TraceData{CorrelationID: id2, Method: "POST", Path: "/b", Timestamp: time.Now()})

	all := GetAllTraces()
	require.Len(t, all, 2)

	// mutate returned data; original storage must not change
	all[id1][0].Method = "MUTATED"
	all[id2] = append(all[id2], TraceData{Method: "PATCH"})

	again := GetAllTraces()
	assert.Equal(t, "GET", again[id1][0].Method)
	require.Len(t, again[id2], 1)
	assert.Equal(t, "POST", again[id2][0].Method)
}

func TestStoreTrace_CleanupOldTracesRemovesOld(t *testing.T) {
	resetTraces(t)

	oldID := "old-1234567890"
	newID := "new-1234567890"

	// Store an old trace (older than 1h)
	storeTrace(oldID, TraceData{
		CorrelationID: oldID,
		Method:        "GET",
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
	})

	// After storing, cleanup should remove the old ID immediately
	tracesOld := GetTraces(oldID)
	assert.Empty(t, tracesOld)

	// Store a recent trace; should persist
	storeTrace(newID, TraceData{
		CorrelationID: newID,
		Method:        "GET",
		Path:          "/new",
		Timestamp:     time.Now(),
	})

	tracesNew := GetTraces(newID)
	require.Len(t, tracesNew, 1)
	assert.Equal(t, "/new", tracesNew[0].Path)
}
