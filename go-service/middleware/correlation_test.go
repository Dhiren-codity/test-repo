package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage(t *testing.T) {
	traceMutex.Lock()
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func Test_isValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"valid_simple_10", "1234567890", true},
		{"valid_with_hyphen_underscore", "abc_def-1234", true},
		{"too_short", "short", false},
		{"too_long", strings.Repeat("a", 101), false},
		{"invalid_chars", "abc$def-123", false},
		{"boundary_100", strings.Repeat("a", 100), true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func Test_generateCorrelationID_IsValid(t *testing.T) {
	id := generateCorrelationID()
	assert.True(t, isValidCorrelationID(id))
	assert.Contains(t, id, "-go-")
	assert.True(t, validIDRegex.MatchString(id))
	assert.GreaterOrEqual(t, len(id), 10)
	assert.LessOrEqual(t, len(id), 100)
}

func Test_extractOrGenerateCorrelationID_ExistingValid(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "valid-id-12345")
	got := extractOrGenerateCorrelationID(r)
	assert.Equal(t, "valid-id-12345", got)
}

func Test_extractOrGenerateCorrelationID_ExistingInvalid(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "bad!")
	got := extractOrGenerateCorrelationID(r)
	assert.NotEqual(t, "bad!", got)
	assert.True(t, isValidCorrelationID(got))
}

func Test_extractOrGenerateCorrelationID_Missing(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	got := extractOrGenerateCorrelationID(r)
	assert.NotEmpty(t, got)
	assert.True(t, isValidCorrelationID(got))
}

func Test_ExtractOrGenerateID_Delegates(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "existing-123456")
	got := ExtractOrGenerateID(r)
	assert.Equal(t, "existing-123456", got)
}

func Test_responseWriter_WriteHeader_SetsStatusAndPassesThrough(t *testing.T) {
	rec := httptest.NewRecorder()
	w := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}
	w.WriteHeader(http.StatusCreated)
	assert.Equal(t, http.StatusCreated, w.statusCode)
	assert.Equal(t, http.StatusCreated, rec.Code)
}

func Test_CorrelationIDMiddleware_SetsHeader_Context_StoresTrace_WriteHeader(t *testing.T) {
	resetTraceStorage(t)

	var ctxID interface{}
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctxID = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusTeapot)
	})

	rr := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/test/path", nil)
	r.Header.Set(CorrelationIDHeader, "valid-corr-id-12345")

	CorrelationIDMiddleware(handler).ServeHTTP(rr, r)

	assert.Equal(t, http.StatusTeapot, rr.Code)
	assert.Equal(t, "valid-corr-id-12345", rr.Header().Get(CorrelationIDHeader))
	assert.Equal(t, "valid-corr-id-12345", ctxID)

	traces := GetTraces("valid-corr-id-12345")
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, "GET", td.Method)
		assert.Equal(t, "/test/path", td.Path)
		assert.Equal(t, "valid-corr-id-12345", td.CorrelationID)
		assert.Equal(t, http.StatusTeapot, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	}

	// Ensure returned traces are copies and not affecting internal storage
	local := GetTraces("valid-corr-id-12345")
	local[0].Service = "mutated"
	again := GetTraces("valid-corr-id-12345")
	assert.Equal(t, "go-parser", again[0].Service)
}

func Test_CorrelationIDMiddleware_StatusDefaultsToOK_WhenOnlyWriteCalled(t *testing.T) {
	resetTraceStorage(t)

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "hello")
	})

	rr := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/onlywrite", nil)
	r.Header.Set(CorrelationIDHeader, "cid-onlywrite-12345")

	CorrelationIDMiddleware(handler).ServeHTTP(rr, r)

	traces := GetTraces("cid-onlywrite-12345")
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusOK, traces[0].Status)
	}
}

func Test_TrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage(t)

	r := httptest.NewRequest(http.MethodPost, "/track/this", nil)
	r.Header.Set(CorrelationIDHeader, "track-1234567890")

	TrackRequest(r, http.StatusAccepted)

	traces := GetTraces("track-1234567890")
	if assert.Len(t, traces, 1) {
		assert.Equal(t, "go-parser", traces[0].Service)
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
		assert.Equal(t, "POST", traces[0].Method)
		assert.Equal(t, "/track/this", traces[0].Path)
	}
}

func Test_TrackRequest_DoesNothingWhenHeaderMissing(t *testing.T) {
	resetTraceStorage(t)

	r := httptest.NewRequest(http.MethodGet, "/noid", nil)
	TrackRequest(r, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func Test_cleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage(t)

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

	assert.False(t, oldExists)
	assert.True(t, newExists)
}

func Test_storeTrace_AppendsAndTriggersCleanup(t *testing.T) {
	resetTraceStorage(t)

	oldID := "old2-1234567890"
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{{Timestamp: time.Now().Add(-90 * time.Minute)}}
	traceMutex.Unlock()

	now := time.Now()
	storeTrace("current-1234567890", TraceData{Timestamp: now, CorrelationID: "current-1234567890"})

	traceMutex.RLock()
	_, oldExists := traceStorage[oldID]
	currentTraces := traceStorage["current-1234567890"]
	traceMutex.RUnlock()

	assert.False(t, oldExists)
	assert.Len(t, currentTraces, 1)
}

func Test_GetAllTraces_ReturnsCopies(t *testing.T) {
	resetTraceStorage(t)

	storeTrace("a-1234567890", TraceData{Service: "s1", Timestamp: time.Now()})
	storeTrace("b-1234567890", TraceData{Service: "s2", Timestamp: time.Now()})

	all1 := GetAllTraces()
	assert.Len(t, all1, 2)

	// Mutate returned copy
	for k := range all1 {
		all1[k] = append(all1[k], TraceData{Service: "mut"})
	}

	// Ensure internal storage unaffected
	all2 := GetAllTraces()
	assert.Len(t, all2, 2)
}
