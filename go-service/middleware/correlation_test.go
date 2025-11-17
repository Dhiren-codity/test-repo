package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
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
		{"valid simple", "1234567890", true},
		{"valid hyphen and underscore", "abc_123-XYZ_456", true},
		{"too short", "short", false},
		{"too long", string(make([]byte, 101)), false},
		{"invalid chars", "abc$%^&*()", false},
		{"mixed valid", "2020-09-30_go_1", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_ValidityAndFormat(t *testing.T) {
	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))

	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.True(t, re.MatchString(id), "generated ID should match pattern")
	// Generate multiple to reduce collision risk
	const n = 10
	ids := make(map[string]struct{}, n)
	for i := 0; i < n; i++ {
		gen := generateCorrelationID()
		assert.True(t, isValidCorrelationID(gen))
		ids[gen] = struct{}{}
		time.Sleep(1 * time.Millisecond)
	}
	assert.Len(t, ids, n, "IDs should be unique across multiple generations")
}

func TestExtractOrGenerateID_UsesExistingValidHeader(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	valid := "valid-12345_id"
	assert.True(t, isValidCorrelationID(valid))
	req.Header.Set(CorrelationIDHeader, valid)

	got := ExtractOrGenerateID(req)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateID_IgnoresInvalidHeaderAndGenerates(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	invalid := "bad id!"
	req.Header.Set(CorrelationIDHeader, invalid)

	got := ExtractOrGenerateID(req)
	assert.NotEqual(t, invalid, got)
	assert.True(t, isValidCorrelationID(got))
}

func TestTrackRequest_StoresTrace_WhenHeaderPresent(t *testing.T) {
	resetTraceStorage()
	id := "track-req-12345"
	req := httptest.NewRequest(http.MethodPost, "/api/v1/items?x=1", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusAccepted)

	traceMutex.RLock()
	defer traceMutex.RUnlock()
	traces := traceStorage[id]
	if assert.Len(t, traces, 1) {
		tr := traces[0]
		assert.Equal(t, "go-parser", tr.Service)
		assert.Equal(t, http.MethodPost, tr.Method)
		assert.Equal(t, "/api/v1/items", tr.Path)
		assert.Equal(t, id, tr.CorrelationID)
		assert.Equal(t, http.StatusAccepted, tr.Status)
	}
}

func TestTrackRequest_SkipsWhenHeaderMissing(t *testing.T) {
	resetTraceStorage()
	req := httptest.NewRequest(http.MethodGet, "/no/header", nil)

	TrackRequest(req, http.StatusOK)

	traceMutex.RLock()
	defer traceMutex.RUnlock()
	assert.Empty(t, traceStorage)
}

func TestStoreTraceAndGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()
	id := "copy-test-12345"
	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	}

	storeTrace(id, td)

	// Get a copy and mutate it
	got := GetTraces(id)
	if assert.Len(t, got, 1) {
		got[0].Method = "MUTATED"
	}

	// Fetch again to ensure underlying storage not mutated
	got2 := GetTraces(id)
	assert.Equal(t, http.MethodGet, got2[0].Method)

	// Non-existent id returns empty slice
	empty := GetTraces("does-not-exist")
	assert.NotNil(t, empty)
	assert.Len(t, empty, 0)
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()
	idA := "all-a-12345"
	idB := "all-b-12345"
	storeTrace(idA, TraceData{CorrelationID: idA, Timestamp: time.Now()})
	storeTrace(idB, TraceData{CorrelationID: idB, Timestamp: time.Now()})

	all := GetAllTraces()
	assert.Len(t, all, 2)
	all[idA][0].Method = "MUTATE"

	again := GetTraces(idA)
	assert.NotEqual(t, "MUTATE", again[0].Method)
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	res := rr.Result()
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, res.StatusCode)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_WithWriteHeader(t *testing.T) {
	resetTraceStorage()
	var ctxID string
	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		val := r.Context().Value(CorrelationIDKey)
		var ok bool
		ctxID, ok = val.(string)
		assert.True(t, ok)
		assert.NotEmpty(t, ctxID)

		time.Sleep(2 * time.Millisecond)
		w.WriteHeader(http.StatusCreated)
	}))
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mw/test", nil)

	h.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, ctxID, respID)

	// Ensure trace stored with correct status and duration
	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		tr := traces[0]
		assert.Equal(t, "go-parser", tr.Service)
		assert.Equal(t, http.MethodGet, tr.Method)
		assert.Equal(t, "/mw/test", tr.Path)
		assert.Equal(t, http.StatusCreated, tr.Status)
		assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
	}
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraceStorage()
	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mw/implicit", nil)

	h.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusOK, traces[0].Status)
	}
}

func TestCorrelationIDMiddleware_UsesValidIncomingHeader_AndIgnoresInvalid(t *testing.T) {
	// Valid incoming header is preserved
	resetTraceStorage()
	valid := "incoming-12345"
	req1 := httptest.NewRequest(http.MethodGet, "/preserve", nil)
	req1.Header.Set(CorrelationIDHeader, valid)
	rr1 := httptest.NewRecorder()
	h1 := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	h1.ServeHTTP(rr1, req1)
	assert.Equal(t, valid, rr1.Header().Get(CorrelationIDHeader))
	assert.NotEmpty(t, GetTraces(valid))

	// Invalid incoming header is replaced
	resetTraceStorage()
	invalid := "bad id!"
	req2 := httptest.NewRequest(http.MethodGet, "/replace", nil)
	req2.Header.Set(CorrelationIDHeader, invalid)
	rr2 := httptest.NewRecorder()
	h2 := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	h2.ServeHTTP(rr2, req2)
	respID := rr2.Header().Get(CorrelationIDHeader)
	assert.NotEqual(t, invalid, respID)
	assert.True(t, isValidCorrelationID(respID))
	assert.NotEmpty(t, GetTraces(respID))
}

func TestCleanupOldTraces_RemovesOldEntriesOnStore(t *testing.T) {
	resetTraceStorage()
	oldID := "old-12345"
	newID := "new-12345"
	now := time.Now()
	oldTime := now.Add(-2 * time.Hour)
	recentTime := now.Add(-5 * time.Minute)

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{CorrelationID: oldID, Timestamp: oldTime},
		{CorrelationID: oldID, Timestamp: recentTime},
	}
	traceStorage[newID] = []TraceData{
		{CorrelationID: newID, Timestamp: recentTime},
	}
	traceMutex.Unlock()

	// Trigger cleanup via storeTrace
	storeTrace("another-12345", TraceData{CorrelationID: "another-12345", Timestamp: now})

	traceMutex.RLock()
	defer traceMutex.RUnlock()
	_, oldExists := traceStorage[oldID]
	_, newExists := traceStorage[newID]

	assert.False(t, oldExists, "old traces should be removed")
	assert.True(t, newExists, "recent traces should remain")
}
