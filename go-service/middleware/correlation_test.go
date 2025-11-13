package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStore(t *testing.T) {
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestExtractOrGenerateID_UsesValidHeader(t *testing.T) {
	resetTraceStore(t)

	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	valid := "1234567890-go-12345"
	r.Header.Set(CorrelationIDHeader, valid)

	got := ExtractOrGenerateID(r)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateID_InvalidHeaderGeneratesNew(t *testing.T) {
	resetTraceStore(t)

	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	r.Header.Set(CorrelationIDHeader, "short") // too short, invalid

	got := ExtractOrGenerateID(r)
	assert.NotEmpty(t, got)
	assert.NotEqual(t, "short", got)
	assert.True(t, isValidCorrelationID(got))
}

func TestExtractOrGenerateID_MissingHeaderGeneratesNew(t *testing.T) {
	resetTraceStore(t)

	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	got := ExtractOrGenerateID(r)
	assert.NotEmpty(t, got)
	assert.True(t, isValidCorrelationID(got))
}

func TestGenerateCorrelationID_IsValidAndFormatted(t *testing.T) {
	resetTraceStore(t)

	id := generateCorrelationID()
	assert.True(t, isValidCorrelationID(id))
	assert.Contains(t, id, "-go-")
	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.True(t, re.MatchString(id), "generated ID should match pattern <unix>-go-<n>")
}

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		ok   bool
	}{
		{"too short", "short", false},
		{"too long", string(make([]byte, 101)), false},
		{"invalid chars", "bad id!", false},
		{"exactly 10 chars", "aaaaaaaaaa", true},
		{"with hyphen", "aaaaa-aaaaa", true},
		{"with underscore", "aaaaa_aaaaa", true},
		{"mixed case", "AbCde-12345", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.ok, isValidCorrelationID(tt.id))
		})
	}
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStore(t)

	r := httptest.NewRequest(http.MethodPost, "/track", nil)
	id := "id-1111111111"
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
		assert.False(t, td.Timestamp.IsZero())
	}
}

func TestTrackRequest_NoHeaderNoStore(t *testing.T) {
	resetTraceStore(t)

	r := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(r, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestStoreTrace_CleanupOldTracesPurgesByFirstTimestamp(t *testing.T) {
	resetTraceStore(t)

	id := "purge-123456"
	oldTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: id,
		Status:        http.StatusOK,
	}
	traceMutex.Lock()
	traceStorage[id] = []TraceData{oldTrace}
	traceMutex.Unlock()

	newTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/new",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	}
	storeTrace(id, newTrace)

	// Because the first trace is older than cutoff, cleanup should have removed the entire key.
	got := GetTraces(id)
	assert.Empty(t, got, "expected traces for id to be purged when first entry is too old")
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStore(t)

	id := "copy-123456"
	r := httptest.NewRequest(http.MethodGet, "/copy", nil)
	r.Header.Set(CorrelationIDHeader, id)
	TrackRequest(r, http.StatusOK)

	traces := GetTraces(id)
	assert.Len(t, traces, 1)
	traces[0].Path = "/mutated"

	traces2 := GetTraces(id)
	assert.Len(t, traces2, 1)
	assert.Equal(t, "/copy", traces2[0].Path)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStore(t)

	r1 := httptest.NewRequest(http.MethodGet, "/a", nil)
	r1.Header.Set(CorrelationIDHeader, "a-1234567890")
	TrackRequest(r1, http.StatusOK)

	r2 := httptest.NewRequest(http.MethodPost, "/b", nil)
	r2.Header.Set(CorrelationIDHeader, "b-1234567890")
	TrackRequest(r2, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 2)

	// mutate returned data
	all["a-1234567890"][0].Path = "/mutated"
	all["new"] = []TraceData{{CorrelationID: "new"}}

	// original store should be unaffected
	tracesA := GetTraces("a-1234567890")
	assert.Equal(t, "/a", tracesA[0].Path)

	realAll := GetAllTraces()
	_, exists := realAll["new"]
	assert.False(t, exists, "mutating returned map must not affect internal store")
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace(t *testing.T) {
	resetTraceStore(t)

	var ctxID interface{}
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctxID = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusTeapot)
		io.WriteString(w, "teapot")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mid", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, ctxID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/mid", td.Path)
		assert.Equal(t, http.StatusTeapot, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
		assert.Equal(t, respID, td.CorrelationID)
	}
}

func TestResponseWriter_WriteHeaderRecordsStatus(t *testing.T) {
	resetTraceStore(t)

	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusAccepted)
	assert.Equal(t, http.StatusAccepted, rw.statusCode)
	assert.Equal(t, http.StatusAccepted, rr.Code)
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraceStore(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// no explicit WriteHeader; implicit 200
		io.WriteString(w, "ok")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/implicit", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusOK, td.Status)
	}
}
