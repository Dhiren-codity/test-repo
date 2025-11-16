package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage() {
	traceMutex.Lock()
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func TestExtractOrGenerateID_UsesExistingValidHeader(t *testing.T) {
	resetTraceStorage()
	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	valid := "valid-12345-ABC_def"
	r.Header.Set(CorrelationIDHeader, valid)

	id := ExtractOrGenerateID(r)
	assert.Equal(t, valid, id)
}

func TestExtractOrGenerateID_InvalidHeaderGeneratesNew(t *testing.T) {
	resetTraceStorage()
	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	r.Header.Set(CorrelationIDHeader, "bad id with spaces")

	id := ExtractOrGenerateID(r)
	assert.NotEqual(t, "bad id with spaces", id)
	assert.NotEmpty(t, id)
	assert.Contains(t, id, "-go-")
}

func TestIsValidCorrelationID_TableDriven(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{name: "too short", id: "short", want: false},
		{name: "too long", id: strings.Repeat("a", 101), want: false},
		{name: "invalid chars", id: "abc$%^12345", want: false},
		{name: "valid with dash underscore", id: "abc_DEF-12345", want: true},
		{name: "valid boundary length 10", id: "abcdefghij", want: true},
		{name: "valid boundary length 100", id: strings.Repeat("a", 100), want: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace_Default200(t *testing.T) {
	resetTraceStorage()

	var seenCtxID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		if s, ok := v.(string); ok {
			seenCtxID = s
		}
		// Do not call WriteHeader to ensure default 200
		_, _ = w.Write([]byte("hello"))
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/hello", nil)

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, seenCtxID)
	assert.Equal(t, http.StatusOK, rr.Code)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/hello", td.Path)
		assert.Equal(t, respID, td.CorrelationID)
		assert.Equal(t, http.StatusOK, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
		assert.WithinDuration(t, time.Now(), td.Timestamp, 5*time.Second)
	}
}

func TestCorrelationIDMiddleware_CapturesExplicitStatus(t *testing.T) {
	resetTraceStorage()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/teapot", nil)
	// Provide a valid correlation ID to be used as-is
	validID := "valid-abc-12345"
	req.Header.Set(CorrelationIDHeader, validID)

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	assert.Equal(t, http.StatusTeapot, rr.Code)
	assert.Equal(t, validID, rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces(validID)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusTeapot, traces[0].Status)
	}
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodPost, "/submit", nil)
	validID := "good-1234567890"
	req.Header.Set(CorrelationIDHeader, validID)

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces(validID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, "/submit", td.Path)
		assert.Equal(t, validID, td.CorrelationID)
		assert.Equal(t, http.StatusCreated, td.Status)
	}
}

func TestTrackRequest_DoesNothingWhenHeaderMissing(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodGet, "/no-id", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()

	id := "copy-test-12345"
	storeTrace(id, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/x",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	})

	traces := GetTraces(id)
	assert.Len(t, traces, 1)
	traces[0].Status = 999

	again := GetTraces(id)
	assert.Len(t, again, 1)
	assert.Equal(t, http.StatusOK, again[0].Status)
}

func TestGetAllTraces_ReturnsDeepCopies(t *testing.T) {
	resetTraceStorage()

	id1 := "id-one-12345"
	id2 := "id-two-12345"
	storeTrace(id1, TraceData{CorrelationID: id1, Timestamp: time.Now(), Status: 200})
	storeTrace(id1, TraceData{CorrelationID: id1, Timestamp: time.Now(), Status: 201})
	storeTrace(id2, TraceData{CorrelationID: id2, Timestamp: time.Now(), Status: 202})

	all := GetAllTraces()
	assert.Len(t, all, 2)

	// mutate returned map and slices
	all[id1][0].Status = 999
	all[id2] = append(all[id2], TraceData{Status: 888})

	// original should remain unchanged
	t1 := GetTraces(id1)
	assert.Equal(t, 2, len(t1))
	assert.Equal(t, 200, t1[0].Status)

	t2 := GetTraces(id2)
	assert.Equal(t, 1, len(t2))
	assert.Equal(t, 202, t2[0].Status)
}

func TestCleanupOldTraces_RemovesOldIDs(t *testing.T) {
	resetTraceStorage()

	id := "old-id-12345"

	// Insert an old trace directly
	traceMutex.Lock()
	traceStorage[id] = []TraceData{
		{CorrelationID: id, Timestamp: time.Now().Add(-2 * time.Hour)},
	}
	traceMutex.Unlock()

	// Storing a new trace for same ID should trigger cleanup and remove the ID
	storeTrace(id, TraceData{CorrelationID: id, Timestamp: time.Now(), Status: 200})

	traces := GetTraces(id)
	assert.Len(t, traces, 0)
}

func TestGenerateCorrelationID_Format(t *testing.T) {
	resetTraceStorage()

	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.Contains(t, id, "-go-")

	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.True(t, re.MatchString(id))
}

func TestResponseWriter_WriteHeaderSetsStatusAndDelegates(t *testing.T) {
	rr := httptest.NewRecorder()
	wrapped := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	wrapped.WriteHeader(http.StatusAccepted)

	assert.Equal(t, http.StatusAccepted, wrapped.statusCode)
	assert.Equal(t, http.StatusAccepted, rr.Code)
}
