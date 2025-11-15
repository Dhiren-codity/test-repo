package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetTraceStorage(t *testing.T) {
	traceMutex.Lock()
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func TestIsValidCorrelationID_TableDriven(t *testing.T) {
	tests := []struct {
		name string
		id   string
		ok   bool
	}{
		{"valid length 10", "abcde-1234", true},
		{"valid length 100", string(make([]byte, 0)), true}, // will replace below
		{"valid underscores", "valid_id_12345", true},
		{"too short", "short", false},
		{"too long", "", false}, // will replace below
		{"invalid space", "valid id 1234", false},
		{"invalid slash", "abc/def_12345", false},
	}

	// Build exact-length strings
	long100 := ""
	for i := 0; i < 100; i++ {
		long100 += "a"
	}
	long101 := long100 + "b"

	tests[1].id = long100
	tests[4].id = long101

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.ok, got)
		})
	}
}

func TestGenerateCorrelationID_Format(t *testing.T) {
	id := generateCorrelationID()
	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.Regexp(t, re, id)
	assert.NotEmpty(t, id)
}

func TestExtractOrGenerateID_UsesExistingValid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set(CorrelationIDHeader, "valid-12345")
	got := ExtractOrGenerateID(req)
	assert.Equal(t, "valid-12345", got)
}

func TestExtractOrGenerateID_RejectsInvalidAndGenerates(t *testing.T) {
	re := regexp.MustCompile(`^\d+-go-\d+$`)

	// Too short
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set(CorrelationIDHeader, "short")
	got := ExtractOrGenerateID(req)
	assert.NotEqual(t, "short", got)
	assert.Regexp(t, re, got)

	// Invalid characters
	req2 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req2.Header.Set(CorrelationIDHeader, "abc/123_456")
	got2 := ExtractOrGenerateID(req2)
	assert.NotEqual(t, "abc/123_456", got2)
	assert.Regexp(t, re, got2)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace(t *testing.T) {
	resetTraceStorage(t)

	var ctxID string
	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			ctxID, _ = v.(string)
		}
		time.Sleep(5 * time.Millisecond)
		w.WriteHeader(http.StatusNoContent)
	}))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/trace", nil)
	h.ServeHTTP(rec, req)

	respID := rec.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)
	assert.Equal(t, respID, ctxID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodGet, tr.Method)
	assert.Equal(t, "/trace", tr.Path)
	assert.Equal(t, respID, tr.CorrelationID)
	assert.Equal(t, http.StatusNoContent, tr.Status)
	assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
}

func TestCorrelationIDMiddleware_DefaultStatusOKWhenNoWriteHeader(t *testing.T) {
	resetTraceStorage(t)

	h := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// do nothing: no WriteHeader, no Write
	}))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ok", nil)
	h.ServeHTTP(rec, req)

	respID := rec.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, "valid-12345")

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces("valid-12345")
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.StatusCreated, tr.Status)
	assert.Equal(t, "/track", tr.Path)
	assert.Equal(t, http.MethodPost, tr.Method)
}

func TestTrackRequest_NoHeaderDoesNothing(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/noop", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage(t)

	id := "valid-12345"
	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/x",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        200,
	}
	storeTrace(id, td)

	// Get copy and mutate
	got := GetTraces(id)
	require.Len(t, got, 1)
	got[0].Service = "mutated"

	// Fetch again from store; should be unaffected
	got2 := GetTraces(id)
	require.Len(t, got2, 1)
	assert.Equal(t, "go-parser", got2[0].Service)
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage(t)

	now := time.Now()
	storeTrace("id1", TraceData{Service: "go-parser", Timestamp: now})
	storeTrace("id2", TraceData{Service: "go-parser", Timestamp: now})

	all := GetAllTraces()
	require.Len(t, all, 2)

	// Mutate returned map and slices
	for k := range all {
		all[k][0].Service = "mutated"
		all[k] = nil
	}
	again := GetAllTraces()
	require.Len(t, again, 2)
	for _, v := range again {
		require.NotNil(t, v)
		require.NotEmpty(t, v)
		assert.Equal(t, "go-parser", v[0].Service)
	}
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage(t)

	oldID := "old-id-1234"
	newID := "new-id-1234"

	// Insert an old trace older than 1 hour
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Service: "go-parser", Timestamp: time.Now().Add(-2 * time.Hour)},
	}
	traceMutex.Unlock()

	// Trigger cleanup via storeTrace
	storeTrace(newID, TraceData{Service: "go-parser", Timestamp: time.Now()})

	all := GetAllTraces()
	_, oldExists := all[oldID]
	_, newExists := all[newID]
	assert.False(t, oldExists)
	assert.True(t, newExists)
}

func TestResponseWriter_WriteHeader_SetsStatusAndForwards(t *testing.T) {
	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	res := rec.Result()
	defer res.Body.Close()

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, res.StatusCode)
}
