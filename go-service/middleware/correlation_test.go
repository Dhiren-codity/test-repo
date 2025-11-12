package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
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
		{"too short", "short", false},
		{"exactly 10", "abcdefghij", true},
		{"exactly 100", func() string {
			s := ""
			for i := 0; i < 100; i++ {
				s += "a"
			}
			return s
		}(), true},
		{"too long 101", func() string {
			s := ""
			for i := 0; i < 101; i++ {
				s += "a"
			}
			return s
		}(), false},
		{"invalid chars", "abc!defghij", false},
		{"underscore allowed", "abc_defghij", true},
		{"hyphen allowed", "abc-defghij", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_UniqueAndValid(t *testing.T) {
	ids := make(map[string]struct{})
	for i := 0; i < 10; i++ {
		id := generateCorrelationID()
		require.NotEmpty(t, id)
		assert.True(t, isValidCorrelationID(id))
		// Check uniqueness across runs
		if _, ok := ids[id]; ok {
			t.Fatalf("duplicate id generated: %s", id)
		}
		ids[id] = struct{}{}
		// small sleep to reduce collision risk
		time.Sleep(100 * time.Microsecond)
	}
}

func TestExtractOrGenerateID_WithValidHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/x", nil)
	valid := "abcdefghij" // length 10 and valid chars
	r.Header.Set(CorrelationIDHeader, valid)

	id := ExtractOrGenerateID(r)
	assert.Equal(t, valid, id)
}

func TestExtractOrGenerateID_WithInvalidHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/x", nil)
	invalid := "short"
	r.Header.Set(CorrelationIDHeader, invalid)

	id := ExtractOrGenerateID(r)
	assert.NotEqual(t, invalid, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateID_NoHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/x", nil)

	id := ExtractOrGenerateID(r)
	assert.True(t, isValidCorrelationID(id))
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage(t)

	r := httptest.NewRequest(http.MethodPost, "/track", nil)
	valid := "abcdefghij"
	r.Header.Set(CorrelationIDHeader, valid)

	TrackRequest(r, http.StatusCreated)

	traces := GetTraces(valid)
	require.Len(t, traces, 1)
	tr := traces[0]

	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodPost, tr.Method)
	assert.Equal(t, "/track", tr.Path)
	assert.Equal(t, valid, tr.CorrelationID)
	assert.Equal(t, http.StatusCreated, tr.Status)
	assert.WithinDuration(t, time.Now(), tr.Timestamp, 2*time.Second)
}

func TestTrackRequest_NoHeaderNoStore(t *testing.T) {
	resetTraceStorage(t)

	r := httptest.NewRequest(http.MethodGet, "/noheader", nil)

	TrackRequest(r, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestStoreTrace_And_GetTraces_Immutability(t *testing.T) {
	resetTraceStorage(t)

	id := "abcdefghij"
	trace1 := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/a",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusOK,
	}
	trace2 := TraceData{
		Service:       "go-parser",
		Method:        http.MethodPost,
		Path:          "/b",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        http.StatusCreated,
	}

	storeTrace(id, trace1)
	storeTrace(id, trace2)

	traces := GetTraces(id)
	require.Len(t, traces, 2)

	// Modify returned copy
	traces[0].Method = "MODIFIED"
	traces[1].Path = "/modified"

	// Fetch again to ensure immutability
	traces2 := GetTraces(id)
	require.Len(t, traces2, 2)
	assert.Equal(t, http.MethodGet, traces2[0].Method)
	assert.Equal(t, "/b", traces2[1].Path)
}

func TestGetAllTraces_CopyImmutability(t *testing.T) {
	resetTraceStorage(t)

	id1 := "abcdefghij"
	id2 := "klmnopqrst"

	storeTrace(id1, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/one",
		Timestamp:     time.Now(),
		CorrelationID: id1,
		Status:        http.StatusOK,
	})
	storeTrace(id2, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/two",
		Timestamp:     time.Now(),
		CorrelationID: id2,
		Status:        http.StatusOK,
	})

	all := GetAllTraces()
	require.Len(t, all, 2)
	require.Len(t, all[id1], 1)
	require.Len(t, all[id2], 1)

	// Modify copy
	all[id1][0].Path = "/mutated"
	delete(all, id2)

	// Original should remain unchanged
	all2 := GetAllTraces()
	require.Len(t, all2, 2)
	traces1 := GetTraces(id1)
	assert.Equal(t, "/one", traces1[0].Path)
	traces2 := GetTraces(id2)
	require.Len(t, traces2, 1)
}

func TestCleanupOldTraces_DeletesOld(t *testing.T) {
	resetTraceStorage(t)

	oldID := "oldoldold1"
	oldTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: oldID,
		Status:        http.StatusOK,
	}

	// Storing an old trace should be cleaned immediately by cleanupOldTraces
	storeTrace(oldID, oldTrace)

	traces := GetTraces(oldID)
	assert.Len(t, traces, 0)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_WithExplicitStatus(t *testing.T) {
	resetTraceStorage(t)

	var seenCtxID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Context().Value(CorrelationIDKey); v != nil {
			if s, ok := v.(string); ok {
				seenCtxID = s
			}
		}
		w.WriteHeader(http.StatusNoContent)
	})

	req := httptest.NewRequest(http.MethodDelete, "/resource", nil)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	res := rr.Result()
	id := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, id)
	assert.Equal(t, id, seenCtxID)

	// Trace stored by middleware
	traces := GetTraces(id)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.Equal(t, "go-parser", tr.Service)
	assert.Equal(t, http.MethodDelete, tr.Method)
	assert.Equal(t, "/resource", tr.Path)
	assert.Equal(t, http.StatusNoContent, tr.Status)
	assert.True(t, tr.DurationMS >= 0)
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraceStorage(t)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "body only")
	})

	req := httptest.NewRequest(http.MethodGet, "/ok", nil)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	res := rr.Result()
	id := res.Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, id)

	traces := GetTraces(id)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestResponseWriter_WriteHeader_SetsStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestCorrelationIDMiddleware_UsesIncomingValidID(t *testing.T) {
	resetTraceStorage(t)

	incomingID := "incoming-valid-id-12345"
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	})

	req := httptest.NewRequest(http.MethodGet, "/incoming", nil)
	req.Header.Set(CorrelationIDHeader, incomingID)
	rr := httptest.NewRecorder()

	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	res := rr.Result()
	id := res.Header.Get(CorrelationIDHeader)
	assert.Equal(t, incomingID, id)

	traces := GetTraces(incomingID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusAccepted, traces[0].Status)
}

func TestCorrelationIDMiddleware_SetsContextValueType(t *testing.T) {
	resetTraceStorage(t)

	var value interface{}
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		value = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/ctx", nil)
	rr := httptest.NewRecorder()
	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	require.NotNil(t, value)
	_, ok := value.(string)
	assert.True(t, ok)
}

func TestTrackRequest_AppendsMultipleForSameID(t *testing.T) {
	resetTraceStorage(t)

	r := httptest.NewRequest(http.MethodGet, "/same", nil)
	id := "abcdefghij"
	r.Header.Set(CorrelationIDHeader, id)

	TrackRequest(r, http.StatusOK)
	TrackRequest(r, http.StatusBadRequest)

	traces := GetTraces(id)
	require.Len(t, traces, 2)
	assert.Equal(t, http.StatusOK, traces[0].Status)
	assert.Equal(t, http.StatusBadRequest, traces[1].Status)
}

func TestCorrelationIDMiddleware_ContextMatchesResponseHeader(t *testing.T) {
	resetTraceStorage(t)

	var seenCtxID string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenCtxID, _ = r.Context().Value(CorrelationIDKey).(string)
		_, _ = w.Write([]byte("ok"))
	})

	req := httptest.NewRequest(http.MethodGet, "/match", nil)
	rr := httptest.NewRecorder()
	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	id := rr.Result().Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, id)
	assert.Equal(t, id, seenCtxID)
}

func TestExtractOrGenerateID_Accepts100CharHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/x", nil)
	s := ""
	for i := 0; i < 100; i++ {
		s += "a"
	}
	r.Header.Set(CorrelationIDHeader, s)
	got := ExtractOrGenerateID(r)
	assert.Equal(t, s, got)
}

func TestCorrelationIDMiddleware_TraceContainsDurationAndTimestamp(t *testing.T) {
	resetTraceStorage(t)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(5 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/dur", nil)
	rr := httptest.NewRecorder()
	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	id := rr.Result().Header.Get(CorrelationIDHeader)
	traces := GetTraces(id)
	require.Len(t, traces, 1)
	tr := traces[0]
	assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
	assert.WithinDuration(t, time.Now(), tr.Timestamp, 2*time.Second)
}

func TestCorrelationIDMiddleware_UsesGeneratedIDWhenIncomingInvalid(t *testing.T) {
	resetTraceStorage(t)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/invalid", nil)
	req.Header.Set(CorrelationIDHeader, "short") // invalid
	rr := httptest.NewRecorder()
	CorrelationIDMiddleware(next).ServeHTTP(rr, req)

	id := rr.Result().Header.Get(CorrelationIDHeader)
	require.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}
