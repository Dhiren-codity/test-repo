package middleware

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
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

func TestIsValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"too short", "short-id", false},                   // len < 10
		{"too long", strings.Repeat("a", 101), false},      // len > 100
		{"valid hyphen underscore", "valid-123_ABC", true}, // allowed chars
		{"contains space", "invalid space", false},         // space not allowed
		{"contains punctuation", "invalid!", false},        // ! not allowed
		{"valid long", "abcde-12345-fghij-67890-klmno_12345", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_ValidAndUnique(t *testing.T) {
	id1 := generateCorrelationID()
	time.Sleep(1 * time.Microsecond)
	id2 := generateCorrelationID()

	assert.NotEmpty(t, id1)
	assert.NotEmpty(t, id2)
	assert.True(t, isValidCorrelationID(id1))
	assert.True(t, isValidCorrelationID(id2))
	assert.NotEqual(t, id1, id2)
}

func TestExtractOrGenerateID_UsesValidHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	valid := "valid-abcde-12345"
	r.Header.Set(CorrelationIDHeader, valid)

	got := ExtractOrGenerateID(r)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateID_GeneratesWhenMissing(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/path", nil)

	got := ExtractOrGenerateID(r)
	assert.True(t, isValidCorrelationID(got))
}

func TestExtractOrGenerateID_IgnoresInvalidHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/path", nil)
	invalid := "invalid id with spaces"
	r.Header.Set(CorrelationIDHeader, invalid)

	got := ExtractOrGenerateID(r)
	assert.NotEqual(t, invalid, got)
	assert.True(t, isValidCorrelationID(got))
}

func TestResponseWriter_WriteHeaderCapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)

	res := rr.Result()
	defer res.Body.Close()

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, res.StatusCode)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_DefaultStatusOK(t *testing.T) {
	resetTraces()

	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		val := r.Context().Value(CorrelationIDKey)
		if s, ok := val.(string); ok {
			ctxID = s
		}
		// no WriteHeader, no body => default 200
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/hello", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	resp := rr.Result()
	defer resp.Body.Close()

	id := resp.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, id)
	assert.Equal(t, ctxID, id)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/hello", td.Path)
		assert.Equal(t, id, td.CorrelationID)
		assert.Equal(t, http.StatusOK, td.Status)
		assert.GreaterOrEqual(t, td.DurationMS, float64(0))
		assert.WithinDuration(t, time.Now(), td.Timestamp, time.Second)
	}
}

func TestCorrelationIDMiddleware_RespectsValidIncomingID(t *testing.T) {
	resetTraces()

	incoming := "incoming-abcdef-12345"
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/create", nil)
	req.Header.Set(CorrelationIDHeader, incoming)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	resp := rr.Result()
	defer resp.Body.Close()

	assert.Equal(t, incoming, resp.Header.Get(CorrelationIDHeader))

	traces := GetTraces(incoming)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusCreated, traces[0].Status)
	}
}

func TestCorrelationIDMiddleware_ReplacesInvalidIncomingID(t *testing.T) {
	resetTraces()

	invalid := "bad id !!!"
	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if s, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			ctxID = s
		}
		w.WriteHeader(http.StatusNoContent)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set(CorrelationIDHeader, invalid)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	resp := rr.Result()
	defer resp.Body.Close()

	outID := resp.Header.Get(CorrelationIDHeader)
	assert.NotEqual(t, invalid, outID)
	assert.True(t, isValidCorrelationID(outID))
	assert.Equal(t, ctxID, outID)

	traces := GetTraces(outID)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusNoContent, traces[0].Status)
	}
}

func TestTrackRequest_StoresTrace_WhenHeaderPresent(t *testing.T) {
	resetTraces()

	id := "trace-abcdef-12345"
	req := httptest.NewRequest(http.MethodGet, "/track", nil)
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusBadRequest)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/track", td.Path)
		assert.Equal(t, id, td.CorrelationID)
		assert.Equal(t, http.StatusBadRequest, td.Status)
	}
}

func TestTrackRequest_DoesNothing_WhenHeaderMissing(t *testing.T) {
	resetTraces()

	req := httptest.NewRequest(http.MethodGet, "/track", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGetTraces_ReturnsCopyAndEmptyWhenMissing(t *testing.T) {
	resetTraces()

	id := "copy-abcdef-12345"
	t1 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: time.Now(), CorrelationID: id, Status: 200}
	t2 := TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/b", Timestamp: time.Now(), CorrelationID: id, Status: 201}
	storeTrace(id, t1)
	storeTrace(id, t2)

	got := GetTraces(id)
	assert.Len(t, got, 2)
	assert.Equal(t, "/a", got[0].Path)
	assert.Equal(t, "/b", got[1].Path)

	// mutate returned slice should not affect internal storage
	got[0].Path = "/mutated"
	got = append(got, TraceData{Path: "/c"})
	got2 := GetTraces(id)
	assert.Len(t, got2, 2)
	assert.Equal(t, "/a", got2[0].Path)

	// missing id returns empty non-nil slice
	empty := GetTraces("missing-id-12345")
	assert.NotNil(t, empty)
	assert.Len(t, empty, 0)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces()

	id1 := "id1-abcdef-12345"
	id2 := "id2-abcdef-12345"
	storeTrace(id1, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: time.Now(), CorrelationID: id1, Status: 200})
	storeTrace(id1, TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/b", Timestamp: time.Now(), CorrelationID: id1, Status: 201})
	storeTrace(id2, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/c", Timestamp: time.Now(), CorrelationID: id2, Status: 404})

	all := GetAllTraces()
	assert.Len(t, all, 2)
	assert.Len(t, all[id1], 2)
	assert.Len(t, all[id2], 1)

	// mutate returned copy should not affect store
	all[id1][0].Path = "/mutated"
	all[id2] = append(all[id2], TraceData{Path: "/extra"})
	all2 := GetAllTraces()
	assert.Equal(t, "/a", all2[id1][0].Path)
	assert.Len(t, all2[id2], 1)
}

func TestCleanupOldTraces_RemovesGroupsWithOldFirstTrace(t *testing.T) {
	resetTraces()

	oldID := "old-abcdef-12345"
	recentID := "recent-abcdef-12345"

	oldTrace1 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/old1", Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: oldID, Status: 200}
	oldTrace2 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/old2", Timestamp: time.Now(), CorrelationID: oldID, Status: 200}

	recentTrace := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/rec", Timestamp: time.Now(), CorrelationID: recentID, Status: 200}

	// Prepopulate with old and recent groups such that old group's first trace is old
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{oldTrace1, oldTrace2}
	traceStorage[recentID] = []TraceData{recentTrace}
	traceMutex.Unlock()

	// Trigger cleanup by storing another trace
	storeTrace("trigger-abcdef-12345", TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/t", Timestamp: time.Now(), CorrelationID: "trigger-abcdef-12345", Status: 200})

	all := GetAllTraces()
	_, oldExists := all[oldID]
	_, recentExists := all[recentID]

	assert.False(t, oldExists, "old group should be removed")
	assert.True(t, recentExists, "recent group should remain")
}

func TestCorrelationIDMiddleware_WritesBodyAndCapturesStatus(t *testing.T) {
	resetTraces()

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
		_, _ = io.WriteString(w, "ok")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/status", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)
	resp := rr.Result()
	defer resp.Body.Close()

	id := resp.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, id)

	traces := GetTraces(id)
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, http.StatusAccepted, td.Status)
		assert.Equal(t, "/status", td.Path)
	}
}

func TestContextValueKeyIsString(t *testing.T) {
	// Ensure that the context key usage remains consistent
	ctx := context.WithValue(context.Background(), CorrelationIDKey, "id-1234567890")
	v := ctx.Value(CorrelationIDKey)
	s, ok := v.(string)
	assert.True(t, ok)
	assert.Equal(t, "id-1234567890", s)
}
