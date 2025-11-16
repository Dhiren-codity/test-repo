package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage() {
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
		{"valid_min_length", "abcdefghij", true}, // length 10
		{"valid_hyphen_underscore", "valid_id-12345", true},
		{"invalid_too_short", "short", false},                 // length < 10
		{"invalid_too_long", strings.Repeat("a", 101), false}, // length > 100
		{"invalid_space", "invalid id 12345", false},
		{"invalid_punct", "invalid.id.12345", false},
		{"invalid_symbols", "invalid!@#12345", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_IsValidAndFormat(t *testing.T) {
	id := generateCorrelationID()
	assert.True(t, isValidCorrelationID(id))
	assert.Contains(t, id, "-go-")
}

func TestExtractOrGenerateCorrelationID_UsesExistingWhenValid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set(CorrelationIDHeader, "valid-abc_12345")
	got := extractOrGenerateCorrelationID(req)
	assert.Equal(t, "valid-abc_12345", got)
}

func TestExtractOrGenerateCorrelationID_GeneratesWhenMissingOrInvalid(t *testing.T) {
	t.Run("missing_header", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		got := extractOrGenerateCorrelationID(req)
		assert.True(t, isValidCorrelationID(got))
	})
	t.Run("invalid_header", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set(CorrelationIDHeader, "bad!")
		got := extractOrGenerateCorrelationID(req)
		assert.True(t, isValidCorrelationID(got))
		assert.NotEqual(t, "bad!", got)
	})
}

func TestExtractOrGenerateID_Wrapper(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set(CorrelationIDHeader, "wrapper-12345_id")
	got := ExtractOrGenerateID(req)
	assert.Equal(t, "wrapper-12345_id", got)
}

func TestCorrelationIDMiddleware_SetsHeader_Context_AndStores(t *testing.T) {
	resetTraceStorage()

	inboundID := "abcde-12345"
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// correlation id should be in context
		val := r.Context().Value(CorrelationIDKey)
		assert.NotNil(t, val)
		if v, ok := val.(string); assert.True(t, ok) {
			assert.Equal(t, inboundID, v)
		}
		_, _ = w.Write([]byte("ok"))
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	req.Header.Set(CorrelationIDHeader, inboundID)

	mw := CorrelationIDMiddleware(handler)
	mw.ServeHTTP(rr, req)

	assert.Equal(t, inboundID, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(inboundID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/path", td.Path)
		assert.Equal(t, inboundID, td.CorrelationID)
		assert.Equal(t, http.StatusOK, td.Status)
		assert.False(t, td.Timestamp.IsZero())
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_CapturesExplicitStatus(t *testing.T) {
	resetTraceStorage()

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
		_, _ = w.Write([]byte("tea"))
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/teapot", nil)

	mw := CorrelationIDMiddleware(handler)
	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusTeapot, rr.Code)

	id := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, id)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusTeapot, traces[0].Status)
		assert.Equal(t, "/teapot", traces[0].Path)
	}
}

func TestResponseWriter_WriteHeaderSetsStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}
	rw.WriteHeader(http.StatusInternalServerError)

	assert.Equal(t, http.StatusInternalServerError, rw.statusCode)
	assert.Equal(t, http.StatusInternalServerError, rr.Code)
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodGet, "/tracked", nil)
	req.Header.Set(CorrelationIDHeader, "track-12345_id")

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces("track-12345_id")
	if assert.Len(t, traces, 1) {
		assert.Equal(t, "go-parser", traces[0].Service)
		assert.Equal(t, "/tracked", traces[0].Path)
		assert.Equal(t, http.StatusCreated, traces[0].Status)
	}
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodGet, "/nheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestStoreTrace_And_GetTraces_CopyBehavior(t *testing.T) {
	resetTraceStorage()

	id := "copy-test-1"
	now := time.Now()
	storeTrace(id, TraceData{Service: "go-parser", Path: "/a", Timestamp: now})
	storeTrace(id, TraceData{Service: "go-parser", Path: "/b", Timestamp: now})

	traces := GetTraces(id)
	assert.Len(t, traces, 2)
	assert.Equal(t, "/a", traces[0].Path)
	assert.Equal(t, "/b", traces[1].Path)

	// mutate returned slice and ensure original store unaffected
	traces[0].Path = "/mutated"
	tracesAgain := GetTraces(id)
	assert.Equal(t, "/a", tracesAgain[0].Path)

	// GetAllTraces returns deep copy
	all := GetAllTraces()
	all[id][0].Path = "/mutated-2"
	allAgain := GetAllTraces()
	assert.Equal(t, "/a", allAgain[id][0].Path)
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage()

	old := time.Now().Add(-2 * time.Hour)
	newt := time.Now()

	traceMutex.Lock()
	traceStorage["old"] = []TraceData{{Service: "go-parser", Timestamp: old}}
	traceStorage["mixed"] = []TraceData{
		{Service: "go-parser", Timestamp: old},
		{Service: "go-parser", Timestamp: newt},
	}
	traceStorage["new"] = []TraceData{{Service: "go-parser", Timestamp: newt}}
	traceMutex.Unlock()

	cleanupOldTraces()

	traceMutex.RLock()
	_, oldExists := traceStorage["old"]
	_, mixedExists := traceStorage["mixed"]
	_, newExists := traceStorage["new"]
	traceMutex.RUnlock()

	assert.False(t, oldExists)
	assert.False(t, mixedExists)
	assert.True(t, newExists)
}

func TestGetTraces_NonExistentReturnsEmptySlice(t *testing.T) {
	resetTraceStorage()
	out := GetTraces("does-not-exist")
	assert.NotNil(t, out)
	assert.Len(t, out, 0)
}
