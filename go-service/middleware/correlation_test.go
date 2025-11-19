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

func resetTraces() {
	traceMutex.Lock()
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func TestIsValidCorrelationID_Table(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{name: "valid typical", id: "abc_123-XYZ9", want: true},
		{name: "too short", id: "short", want: false},
		{name: "too long", id: strings.Repeat("a", 101), want: false},
		{name: "invalid chars", id: "abc$123", want: false},
		{name: "boundary 10", id: "abcdefghij", want: true},
		{name: "boundary 100", id: strings.Repeat("a", 100), want: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_FormatAndUniqueness(t *testing.T) {
	resetTraces()

	re := regexp.MustCompile(`^\d+-go-\d+$`)

	id1 := generateCorrelationID()
	assert.NotEmpty(t, id1)
	assert.Regexp(t, re, id1)

	time.Sleep(time.Millisecond)
	id2 := generateCorrelationID()
	assert.NotEmpty(t, id2)
	assert.Regexp(t, re, id2)
	assert.NotEqual(t, id1, id2)
}

func TestExtractOrGenerateID_HeaderValidAndInvalid(t *testing.T) {
	resetTraces()

	re := regexp.MustCompile(`^\d+-go-\d+$`)

	tests := []struct {
		name       string
		header     string
		wantMatch  *regexp.Regexp
		shouldEcho bool
	}{
		{name: "valid header echoed", header: "valid-ABC_def-123", wantMatch: nil, shouldEcho: true},
		{name: "invalid header short generates", header: "short", wantMatch: re, shouldEcho: false},
		{name: "invalid header chars generates", header: "bad$$id!!__--", wantMatch: re, shouldEcho: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/path", nil)
			if tt.header != "" {
				req.Header.Set(CorrelationIDHeader, tt.header)
			}
			got := ExtractOrGenerateID(req)
			if tt.shouldEcho {
				assert.Equal(t, tt.header, got)
			} else {
				assert.NotEqual(t, tt.header, got)
				assert.Regexp(t, tt.wantMatch, got)
			}
		})
	}
}

func TestCorrelationIDMiddleware_PropagatesAndStores_WithExistingID(t *testing.T) {
	resetTraces()

	expectedID := "valid-12345_abc"
	var ctxID any
	base := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctxID = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusAccepted)
	})
	h := CorrelationIDMiddleware(base)

	req := httptest.NewRequest(http.MethodGet, "/foo", nil)
	req.Header.Set(CorrelationIDHeader, expectedID)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusAccepted, rr.Code)
	assert.Equal(t, expectedID, rr.Header().Get(CorrelationIDHeader))
	assert.Equal(t, expectedID, ctxID)

	traces := GetTraces(expectedID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/foo", td.Path)
		assert.Equal(t, expectedID, td.CorrelationID)
		assert.Equal(t, http.StatusAccepted, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
		assert.WithinDuration(t, time.Now(), td.Timestamp, time.Second)
	}
}

func TestCorrelationIDMiddleware_GeneratesIDWhenMissing(t *testing.T) {
	resetTraces()

	var ctxID string
	base := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			ctxID = v
		}
		w.WriteHeader(http.StatusOK)
	})
	h := CorrelationIDMiddleware(base)

	req := httptest.NewRequest(http.MethodGet, "/bar", nil)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, ctxID)

	traces := GetTraces(respID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusOK, td.Status)
		assert.Equal(t, "/bar", td.Path)
		assert.Equal(t, http.MethodGet, td.Method)
	}
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestResponseWriter_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	_, _ = rw.Write([]byte("hello")) // not intercepted, but recorder sets 200
	assert.Equal(t, http.StatusOK, rw.statusCode)
	assert.Equal(t, http.StatusOK, rr.Code)
}

func TestStoreTraceAndGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces()

	id := "copy-test"
	td := TraceData{
		CorrelationID: id,
		Status:        200,
		Timestamp:     time.Now(),
	}
	storeTrace(id, td)

	got := GetTraces(id)
	if assert.Len(t, got, 1) {
		assert.Equal(t, 200, got[0].Status)
		// mutate returned slice
		got[0].Status = 500
	}

	got2 := GetTraces(id)
	if assert.Len(t, got2, 1) {
		assert.Equal(t, 200, got2[0].Status)
	}
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces()

	id1 := "x"
	id2 := "y"

	storeTrace(id1, TraceData{CorrelationID: id1, Status: 201, Timestamp: time.Now()})
	storeTrace(id1, TraceData{CorrelationID: id1, Status: 202, Timestamp: time.Now()})
	storeTrace(id2, TraceData{CorrelationID: id2, Status: 301, Timestamp: time.Now()})

	all := GetAllTraces()
	assert.Contains(t, all, id1)
	assert.Contains(t, all, id2)
	assert.Len(t, all[id1], 2)
	assert.Len(t, all[id2], 1)

	// mutate the returned map and slices
	all[id1][0].Status = 999
	all[id2] = nil

	// ensure original store unaffected
	orig1 := GetTraces(id1)
	orig2 := GetTraces(id2)
	assert.Equal(t, 201, orig1[0].Status)
	assert.Len(t, orig2, 1)
}

func TestCleanupOldTraces_RemovesExpired(t *testing.T) {
	resetTraces()

	oldID := "old"
	newID := "new"
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{CorrelationID: oldID, Timestamp: time.Now().Add(-2 * time.Hour), Status: 200},
	}
	traceStorage[newID] = []TraceData{
		{CorrelationID: newID, Timestamp: time.Now(), Status: 200},
	}
	traceMutex.Unlock()

	// trigger cleanup via storeTrace
	storeTrace("trigger", TraceData{CorrelationID: "trigger", Timestamp: time.Now(), Status: 200})

	oldTraces := GetTraces(oldID)
	newTraces := GetTraces(newID)
	triggerTraces := GetTraces("trigger")

	assert.Len(t, oldTraces, 0)
	assert.Len(t, newTraces, 1)
	assert.Len(t, triggerTraces, 1)
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraces()

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	id := "track-123456789"
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusBadGateway)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, id, td.CorrelationID)
		assert.Equal(t, "/track", td.Path)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, http.StatusBadGateway, td.Status)
	}
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraces()

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGetTraces_ReturnsEmptySliceWhenMissing(t *testing.T) {
	resetTraces()

	got := GetTraces("missing")
	assert.NotNil(t, got)
	assert.Len(t, got, 0)
}
