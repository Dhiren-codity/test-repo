package middleware

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetTraceStorage(t *testing.T) {
	t.Helper()
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
		{name: "valid length 10", id: "abcdefghij", want: true},
		{name: "valid with hyphen underscore digits", id: "12345-6789_ab", want: true},
		{name: "too short", id: "short", want: false},
		{name: "too long", id: strings.Repeat("a", 101), want: false},
		{name: "invalid characters", id: "invalid*!@", want: false},
		{name: "length 100 valid", id: strings.Repeat("a", 100), want: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_UniqueAndFormat(t *testing.T) {
	resetTraceStorage(t)

	pat := regexp.MustCompile(`^\d+-go-\d+$`)

	id1 := generateCorrelationID()
	time.Sleep(2 * time.Millisecond)
	id2 := generateCorrelationID()

	require.NotEmpty(t, id1)
	require.NotEmpty(t, id2)
	assert.NotEqual(t, id1, id2)
	assert.True(t, pat.MatchString(id1))
	assert.True(t, pat.MatchString(id2))
	assert.True(t, isValidCorrelationID(id1))
	assert.True(t, isValidCorrelationID(id2))
}

func TestExtractOrGenerateCorrelationID(t *testing.T) {
	resetTraceStorage(t)

	// No header -> generate
	req1 := httptest.NewRequest(http.MethodGet, "/", nil)
	id1 := extractOrGenerateCorrelationID(req1)
	require.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// Valid header -> use existing
	req2 := httptest.NewRequest(http.MethodGet, "/", nil)
	req2.Header.Set(CorrelationIDHeader, strings.Repeat("a", 10))
	id2 := extractOrGenerateCorrelationID(req2)
	assert.Equal(t, strings.Repeat("a", 10), id2)

	// Invalid header -> generate new
	req3 := httptest.NewRequest(http.MethodGet, "/", nil)
	req3.Header.Set(CorrelationIDHeader, "bad!!")
	id3 := extractOrGenerateCorrelationID(req3)
	require.NotEmpty(t, id3)
	assert.NotEqual(t, "bad!!", id3)
	assert.True(t, isValidCorrelationID(id3))
}

func TestExtractOrGenerateID_Exported(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(req)
	require.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))

	req.Header.Set(CorrelationIDHeader, strings.Repeat("b", 10))
	id2 := ExtractOrGenerateID(req)
	assert.Equal(t, strings.Repeat("b", 10), id2)
}

func TestCorrelationIDMiddleware_SetsHeaderAndTracks_Default200_Context(t *testing.T) {
	resetTraceStorage(t)

	var ctxIDFromHandler string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				ctxIDFromHandler = s
				w.Header().Set("X-Context-ID", s)
			}
		}
		_, _ = io.WriteString(w, "ok") // no explicit WriteHeader -> 200
	})

	srv := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ping", nil)
	srv.ServeHTTP(rr, req)

	res := rr.Result()
	cid := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, cid)
	assert.Equal(t, cid, ctxIDFromHandler, "context should carry correlation id into handler")
	assert.Equal(t, cid, res.Header.Get("X-Context-ID"))

	traces := GetTraces(cid)
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodGet, td.Method)
	assert.Equal(t, "/ping", td.Path)
	assert.Equal(t, cid, td.CorrelationID)
	assert.Equal(t, http.StatusOK, td.Status)
	assert.GreaterOrEqual(t, td.DurationMS, 0.0)
}

func TestCorrelationIDMiddleware_RespectsClientHeader_AndCapturesLastStatus(t *testing.T) {
	resetTraceStorage(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTeapot)              // first status
		w.WriteHeader(http.StatusInternalServerError) // second status
		_, _ = io.WriteString(w, "body")
	})

	srv := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/brew", nil)
	req.Header.Set(CorrelationIDHeader, "client-provided-123")
	srv.ServeHTTP(rr, req)

	res := rr.Result()
	assert.Equal(t, "client-provided-123", res.Header.Get(CorrelationIDHeader))
	// httptest.ResponseRecorder honors first status; our wrapper will record the last one
	assert.Equal(t, http.StatusTeapot, res.Code)

	traces := GetTraces("client-provided-123")
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, http.StatusInternalServerError, td.Status) // captured last WriteHeader per current implementation
	assert.Equal(t, "/brew", td.Path)
}

func TestTrackRequest_HeaderOptional(t *testing.T) {
	resetTraceStorage(t)

	// No header -> no trace
	req1 := httptest.NewRequest(http.MethodGet, "/no-trace", nil)
	TrackRequest(req1, http.StatusCreated)
	all1 := GetAllTraces()
	assert.Len(t, all1, 0)

	// With header -> trace stored
	req2 := httptest.NewRequest(http.MethodPost, "/trace", nil)
	req2.Header.Set(CorrelationIDHeader, "trace-123456")
	TrackRequest(req2, http.StatusCreated)

	traces := GetTraces("trace-123456")
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodPost, td.Method)
	assert.Equal(t, "/trace", td.Path)
	assert.Equal(t, http.StatusCreated, td.Status)
}

func TestGetTracesAndAllTraces_CopyBehavior(t *testing.T) {
	resetTraceStorage(t)

	// Seed two IDs
	id1 := "aaaaaaaaaa"
	id2 := "bbbbbbbbbb"
	now := time.Now()
	storeTrace(id1, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: now, CorrelationID: id1, Status: 200})
	storeTrace(id2, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/b", Timestamp: now, CorrelationID: id2, Status: 201})

	// GetTraces returns a copy; mutating it should not affect underlying
	trs1 := GetTraces(id1)
	require.Len(t, trs1, 1)
	trs1[0].Status = 999

	trs1Again := GetTraces(id1)
	require.Len(t, trs1Again, 1)
	assert.Equal(t, 200, trs1Again[0].Status)

	// GetAllTraces returns deep-copied map and slices
	all := GetAllTraces()
	require.Len(t, all, 2)

	// Mutate returned map and slice
	delete(all, id1)
	all[id2] = append(all[id2], TraceData{CorrelationID: id2, Status: 418})

	// Original storage should remain unaffected
	allAgain := GetAllTraces()
	require.Len(t, allAgain, 2)
	assert.Len(t, allAgain[id1], 1)
	assert.Len(t, allAgain[id2], 1)
}

func TestCleanupOldTraces_RemovesExpired(t *testing.T) {
	resetTraceStorage(t)

	recentID := "recentid01"
	oldID := "oldid-----"

	recentTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/recent",
		Timestamp:     time.Now().Add(-30 * time.Minute),
		CorrelationID: recentID,
		Status:        200,
	}
	oldTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: oldID,
		Status:        200,
	}

	// Add recent first, then old; cleanup runs after each store
	storeTrace(recentID, recentTrace)
	storeTrace(oldID, oldTrace)

	// Old should have been purged; recent should remain
	assert.Len(t, GetTraces(oldID), 0)
	assert.Len(t, GetTraces(recentID), 1)
}

func TestResponseWriter_WriteHeader_CapturesLastAndPassesThrough(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(201)
	rw.WriteHeader(418) // our wrapper will update statusCode again

	assert.Equal(t, 418, rw.statusCode)
	// ResponseRecorder honors the first header only
	assert.Equal(t, 201, rr.Code)
}

func TestCorrelationIDMiddleware_ContextValueType(t *testing.T) {
	resetTraceStorage(t)

	var ctxVal interface{}
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctxVal = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusOK)
	})

	srv := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ctx", nil)
	srv.ServeHTTP(rr, req)

	require.NotNil(t, ctxVal)
	_, ok := ctxVal.(string)
	assert.True(t, ok, "context value should be a string correlation id")
}

func TestStoreTraceAndGetTraces_OrderPreserved(t *testing.T) {
	resetTraceStorage(t)

	id := "order-id-01"
	now := time.Now()
	storeTrace(id, TraceData{Path: "/1", Timestamp: now, CorrelationID: id})
	storeTrace(id, TraceData{Path: "/2", Timestamp: now.Add(1 * time.Second), CorrelationID: id})
	storeTrace(id, TraceData{Path: "/3", Timestamp: now.Add(2 * time.Second), CorrelationID: id})

	trs := GetTraces(id)
	require.Len(t, trs, 3)
	assert.Equal(t, "/1", trs[0].Path)
	assert.Equal(t, "/2", trs[1].Path)
	assert.Equal(t, "/3", trs[2].Path)
}

func TestCorrelationIDMiddleware_SetsResponseHeaderEvenWithInvalidClientHeader(t *testing.T) {
	resetTraceStorage(t)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	srv := CorrelationIDMiddleware(h)

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, "bad!!")
	srv.ServeHTTP(rr, req)

	res := rr.Result()
	cid := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, cid)
	assert.NotEqual(t, "bad!!", cid)

	// Trace stored under generated ID
	trs := GetTraces(cid)
	require.Len(t, trs, 1)
	assert.Equal(t, http.StatusOK, trs[0].Status)
}

func TestTrackRequest_MultipleEntriesUnderSameID(t *testing.T) {
	resetTraceStorage(t)

	id := "multi-id-xx"
	req := httptest.NewRequest(http.MethodGet, "/a", nil)
	req.Header.Set(CorrelationIDHeader, id)
	TrackRequest(req, http.StatusOK)

	req2 := httptest.NewRequest(http.MethodPost, "/b", nil)
	req2.Header.Set(CorrelationIDHeader, id)
	TrackRequest(req2, http.StatusCreated)

	trs := GetTraces(id)
	require.Len(t, trs, 2)
	assert.Equal(t, "/a", trs[0].Path)
	assert.Equal(t, http.StatusOK, trs[0].Status)
	assert.Equal(t, "/b", trs[1].Path)
	assert.Equal(t, http.StatusCreated, trs[1].Status)
}

func TestCorrelationIDMiddleware_ContextPropagationAcrossHandlers(t *testing.T) {
	resetTraceStorage(t)

	// Simulate a middleware chain where downstream reads context
	downstream := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "ok")
	})

	mw := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// read from context and set a header
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				w.Header().Set("X-Ctx-Seen", s)
			}
		}
		downstream.ServeHTTP(w, r)
	})

	srv := CorrelationIDMiddleware(mw)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/chain", nil)
	srv.ServeHTTP(rr, req)

	res := rr.Result()
	cid := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, cid)
	assert.Equal(t, cid, res.Header.Get("X-Ctx-Seen"))

	trs := GetTraces(cid)
	require.Len(t, trs, 1)
	assert.Equal(t, "/chain", trs[0].Path)
}

func TestStoreTrace_CleanupDoesNotAffectRecentIDs(t *testing.T) {
	resetTraceStorage(t)

	idRecent1 := "recent-1--"
	idRecent2 := "recent-2--"
	now := time.Now()

	storeTrace(idRecent1, TraceData{Timestamp: now.Add(-30 * time.Minute), CorrelationID: idRecent1})
	storeTrace(idRecent2, TraceData{Timestamp: now.Add(-10 * time.Minute), CorrelationID: idRecent2})

	assert.Len(t, GetTraces(idRecent1), 1)
	assert.Len(t, GetTraces(idRecent2), 1)

	// Add and immediately purge an old id
	storeTrace("old-xxxxx-", TraceData{Timestamp: now.Add(-2 * time.Hour), CorrelationID: "old-xxxxx-"})

	// Recents remain
	assert.Len(t, GetTraces(idRecent1), 1)
	assert.Len(t, GetTraces(idRecent2), 1)
}

func TestExtractOrGenerateID_PrefersFirstHeaderValue(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header[CorrelationIDHeader] = []string{"first-value-1", "second-value-2"}
	id := ExtractOrGenerateID(req)
	assert.Equal(t, "first-value-1", id)
}

func TestCorrelationIDMiddleware_ContextKeyIsolation(t *testing.T) {
	resetTraceStorage(t)

	var seen string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify only our key is used
		_ = context.WithValue(r.Context(), "otherKey", "x")
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				seen = s
			}
		}
		w.WriteHeader(http.StatusOK)
	})

	srv := CorrelationIDMiddleware(h)
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/k", nil)
	srv.ServeHTTP(rr, req)

	res := rr.Result()
	cid := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, cid)
	assert.Equal(t, cid, seen)
}
