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

func resetTraceStorage(t *testing.T) {
	t.Helper()
	traceMutex.Lock()
	defer traceMutex.Unlock()
	traceStorage = make(map[string][]TraceData)
}

func TestExtractOrGenerateID_UsesValidExistingHeader(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	valid := "abc_DEF-12345"
	req.Header.Set(CorrelationIDHeader, valid)

	got := ExtractOrGenerateID(req)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateID_GeneratesWhenMissingOrInvalid(t *testing.T) {
	resetTraceStorage(t)

	tests := []struct {
		name       string
		headerVal  string
		shouldKeep bool
	}{
		{name: "missing header", headerVal: "", shouldKeep: false},
		{name: "invalid short", headerVal: "short", shouldKeep: false},
		{name: "invalid chars", headerVal: "bad#id#chars", shouldKeep: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			if tt.headerVal != "" {
				req.Header.Set(CorrelationIDHeader, tt.headerVal)
			}
			got := ExtractOrGenerateID(req)
			if tt.shouldKeep {
				assert.Equal(t, tt.headerVal, got)
			} else {
				assert.NotEmpty(t, got)
				assert.NotEqual(t, tt.headerVal, got)
				assert.Regexp(t, regexp.MustCompile(`^[0-9]+-go-[0-9]+$`), got)
			}
		})
	}
}

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		id    string
		valid bool
	}{
		{"abc_DEF-12345", true},
		{"short-1", false},                                           // too short
		{strings.Repeat("a", 101), false},                            // too long
		{"invalid#chars-1234", false},                                // invalid chars
		{"______-----aaaaaBBBBB11111", true},                         // valid chars and length
		{"with space 123456", false},                                 // space not allowed
		{"valid_1234567890-valid_1234567890-valid_1234567890", true}, // long but within limit
	}
	for _, tt := range tests {
		assert.Equal(t, tt.valid, isValidCorrelationID(tt.id), tt.id)
	}
}

func TestTrackRequest_WithoutHeaderDoesNothing(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusAccepted)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestTrackRequest_StoresTraceWhenHeaderPresent(t *testing.T) {
	resetTraceStorage(t)

	cid := "valid_ID-12345"
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusCreated)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodPost, td.Method)
		assert.Equal(t, "/track", td.Path)
		assert.Equal(t, cid, td.CorrelationID)
		assert.Equal(t, http.StatusCreated, td.Status)
		assert.True(t, time.Since(td.Timestamp) < time.Second*5)
		assert.Equal(t, 0.0, td.DurationMS)
	}
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace(t *testing.T) {
	resetTraceStorage(t)

	var handlerCtxCID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		v := r.Context().Value(CorrelationIDKey)
		if v != nil {
			if s, ok := v.(string); ok {
				handlerCtxCID = s
			}
		}
		w.WriteHeader(http.StatusTeapot)
	})

	mw := CorrelationIDMiddleware(next)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mw", nil)

	mw.ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()

	respCID := resp.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, respCID)
	assert.Equal(t, respCID, handlerCtxCID)

	traces := GetTraces(respCID)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/mw", td.Path)
		assert.Equal(t, respCID, td.CorrelationID)
		assert.Equal(t, http.StatusTeapot, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, 0.0)
		assert.True(t, time.Since(td.Timestamp) < time.Second*5)
	}
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage(t)

	cid := "copy_test_12345"
	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: cid,
		Status:        0,
	}
	storeTrace(cid, td)

	got := GetTraces(cid)
	assert.Len(t, got, 1)
	got[0].Status = 999

	got2 := GetTraces(cid)
	assert.Len(t, got2, 1)
	assert.Equal(t, 0, got2[0].Status)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStorage(t)

	now := time.Now()
	id1 := "id1_valid_12345"
	id2 := "id2_valid_12345"

	storeTrace(id1, TraceData{Service: "go-parser", Method: "GET", Path: "/a", Timestamp: now, CorrelationID: id1, Status: 200})
	storeTrace(id2, TraceData{Service: "go-parser", Method: "POST", Path: "/b", Timestamp: now, CorrelationID: id2, Status: 201})

	all := GetAllTraces()
	assert.Len(t, all, 2)
	assert.Len(t, all[id1], 1)
	assert.Len(t, all[id2], 1)

	// mutate returned map and slices; internal storage should not reflect these changes
	all[id1][0].Status = 500
	all[id2] = nil
	all["new"] = []TraceData{{CorrelationID: "new"}}

	// verify internal storage unchanged
	tr1 := GetTraces(id1)
	tr2 := GetTraces(id2)
	assert.Len(t, tr1, 1)
	assert.Equal(t, 200, tr1[0].Status)
	assert.Len(t, tr2, 1)
	assert.Equal(t, 201, tr2[0].Status)
	assert.Len(t, GetTraces("new"), 0)
}

func TestCleanupOldTraces_RemovesOldEntriesOnStore(t *testing.T) {
	resetTraceStorage(t)

	oldID := "old_valid_123456"
	newID := "new_valid_123456"

	// seed old traces directly under lock to simulate pre-existing data
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Service: "go-parser", Method: "GET", Path: "/old", Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: oldID, Status: 200},
	}
	traceMutex.Unlock()

	// trigger cleanup by storing a new trace
	storeTrace(newID, TraceData{Service: "go-parser", Method: "GET", Path: "/new", Timestamp: time.Now(), CorrelationID: newID, Status: 200})

	assert.Len(t, GetTraces(oldID), 0)
	assert.Len(t, GetTraces(newID), 1)
}

func TestResponseWriter_WriteHeader_SetsStatusAndPassesThrough(t *testing.T) {
	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: 0}

	rw.WriteHeader(http.StatusCreated)
	assert.Equal(t, http.StatusCreated, rw.statusCode)
	assert.Equal(t, http.StatusCreated, rec.Code)

	// subsequent call updates our wrapper's status; ResponseRecorder will reflect the latest call as well
	rw.WriteHeader(http.StatusInternalServerError)
	assert.Equal(t, http.StatusInternalServerError, rw.statusCode)
	assert.Equal(t, http.StatusInternalServerError, rec.Code)
}
