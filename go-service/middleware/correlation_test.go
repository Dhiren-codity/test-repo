package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
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

func Test_isValidCorrelationID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{name: "valid min length digits", id: "1234567890", want: true},
		{name: "valid with hyphen underscore", id: "abc-DEF_123456", want: true},
		{name: "too short", id: "short", want: false},
		{name: "too long", id: strings.Repeat("a", 101), want: false},
		{name: "invalid chars", id: "invalid!*@#12345", want: false},
		{name: "unicode invalid", id: "ümlaut-123456", want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func Test_generateCorrelationID_Validity(t *testing.T) {
	for i := 0; i < 5; i++ {
		id := generateCorrelationID()
		require.NotEmpty(t, id)
		assert.Contains(t, id, "-go-")
		assert.True(t, isValidCorrelationID(id))
	}
}

func Test_extractOrGenerateCorrelationID_HeaderValid(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	valid := "valid-1234567890"
	req.Header.Set(CorrelationIDHeader, valid)

	got := extractOrGenerateCorrelationID(req)
	assert.Equal(t, valid, got)
}

func Test_extractOrGenerateCorrelationID_HeaderInvalidOrMissing(t *testing.T) {
	// Missing
	req1 := httptest.NewRequest(http.MethodGet, "/", nil)
	id1 := extractOrGenerateCorrelationID(req1)
	assert.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// Present but invalid
	req2 := httptest.NewRequest(http.MethodGet, "/", nil)
	req2.Header.Set(CorrelationIDHeader, "short")
	id2 := extractOrGenerateCorrelationID(req2)
	assert.NotEqual(t, "short", id2)
	assert.True(t, isValidCorrelationID(id2))
}

func Test_ExtractOrGenerateID_Wrapper(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(req)
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))

	req.Header.Set(CorrelationIDHeader, "valid-AAAAAAAA")
	id2 := ExtractOrGenerateID(req)
	assert.Equal(t, "valid-AAAAAAAA", id2)
}

func Test_responseWriter_WriteHeader(t *testing.T) {
	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rec.Code)

	// Subsequent calls overwrite statusCode in this implementation
	rw.WriteHeader(http.StatusCreated)
	assert.Equal(t, http.StatusCreated, rw.statusCode)
	assert.Equal(t, http.StatusCreated, rec.Code)
}

func Test_CorrelationIDMiddleware_UsesExistingID_SetsContext_StoresTrace(t *testing.T) {
	resetTraceStorage(t)

	wantID := "valid-1234567890"
	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v, ok := r.Context().Value(CorrelationIDKey).(string); ok {
			ctxID = v
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, "ok")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/things", nil)
	req.Header.Set(CorrelationIDHeader, wantID)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	res := rr.Result()
	gotHeader := res.Header.Get(CorrelationIDHeader)
	require.Equal(t, wantID, gotHeader)
	assert.Equal(t, wantID, ctxID)

	traces := GetTraces(wantID)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodGet, tr.Method)
	assert.Equal(t, "/things", tr.Path)
	assert.Equal(t, wantID, tr.CorrelationID)
	assert.Equal(t, http.StatusCreated, tr.Status)
	assert.False(t, tr.Timestamp.IsZero())
	assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
}

func Test_CorrelationIDMiddleware_GeneratesIDWhenMissing(t *testing.T) {
	resetTraceStorage(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "body")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/gen", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	res := rr.Result()
	gotHeader := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, gotHeader)
	assert.True(t, isValidCorrelationID(gotHeader))

	traces := GetTraces(gotHeader)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, http.StatusOK, tr.Status)
	assert.Equal(t, "/gen", tr.Path)
}

func Test_TrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	id := "track-1234567890"
	req.Header.Set(CorrelationIDHeader, id)

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces(id)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, id, tr.CorrelationID)
	assert.Equal(t, http.StatusAccepted, tr.Status)
	assert.Equal(t, "/track", tr.Path)
	assert.Equal(t, http.MethodPost, tr.Method)
}

func Test_TrackRequest_IgnoresWhenHeaderMissing(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func Test_GetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage(t)

	id := "copy-1234567890"
	orig := TraceData{
		Service:       "orig",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        200,
	}
	storeTrace(id, orig)

	ret1 := GetTraces(id)
	require.Len(t, ret1, 1)
	ret1[0].Service = "mutated"

	ret2 := GetTraces(id)
	require.Len(t, ret2, 1)
	assert.Equal(t, "orig", ret2[0].Service)
}

func Test_GetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStorage(t)

	id1 := "all-1111111111"
	id2 := "all-2222222222"
	storeTrace(id1, TraceData{Service: "s1", Timestamp: time.Now(), CorrelationID: id1})
	storeTrace(id2, TraceData{Service: "s2", Timestamp: time.Now(), CorrelationID: id2})

	all1 := GetAllTraces()
	require.Len(t, all1, 2)
	all1[id1][0].Service = "changed"
	all1["new"] = []TraceData{{Service: "new"}}

	all2 := GetAllTraces()
	require.Len(t, all2, 2)
	assert.Equal(t, "s1", all2[id1][0].Service)
	_, exists := all2["new"]
	assert.False(t, exists)
}

func Test_GetTraces_NonExistingReturnsEmpty(t *testing.T) {
	resetTraceStorage(t)

	out := GetTraces("does-not-exist")
	assert.NotNil(t, out)
	assert.Len(t, out, 0)
}

func Test_cleanupOldTraces_RemovesOldIDs(t *testing.T) {
	resetTraceStorage(t)

	oldID := "old-1234567890"
	recentID := "recent-1234567890"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{{CorrelationID: oldID, Timestamp: time.Now().Add(-2 * time.Hour)}}
	traceStorage[recentID] = []TraceData{{CorrelationID: recentID, Timestamp: time.Now()}}
	traceMutex.Unlock()

	cleanupOldTraces()

	all := GetAllTraces()
	_, oldExists := all[oldID]
	_, recentExists := all[recentID]

	assert.False(t, oldExists)
	assert.True(t, recentExists)
}
