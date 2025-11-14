package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetTraceStorage() {
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
		{"too short", "short", false},
		{"invalid char", "abc$defghi", false},
		{"valid hyphen", "abc-1234567890", true},
		{"valid underscore", "abc_1234567", true},
		{"min length 10", "1234567890", true},
		{"max length 100", func() string {
			b := make([]byte, 100)
			for i := range b {
				b[i] = 'a'
			}
			return string(b)
		}(), true},
		{"over max length 101", func() string {
			b := make([]byte, 101)
			for i := range b {
				b[i] = 'a'
			}
			return string(b)
		}(), false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestGenerateCorrelationID_IsValid(t *testing.T) {
	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateCorrelationID(t *testing.T) {
	t.Run("uses existing valid header", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set(CorrelationIDHeader, "valid-1234567890")
		got := extractOrGenerateCorrelationID(r)
		assert.Equal(t, "valid-1234567890", got)
	})

	t.Run("generates when missing", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		got := extractOrGenerateCorrelationID(r)
		assert.NotEmpty(t, got)
	})

	t.Run("generates when invalid", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set(CorrelationIDHeader, "bad$id")
		got := extractOrGenerateCorrelationID(r)
		assert.NotEqual(t, "bad$id", got)
		assert.True(t, isValidCorrelationID(got))
	})
}

func TestExtractOrGenerateID_Exported(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "valid-1234567890")
	got := ExtractOrGenerateID(r)
	assert.Equal(t, "valid-1234567890", got)
}

func TestResponseWriter_WriteHeader(t *testing.T) {
	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rec.Code)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_WithExplicitStatus(t *testing.T) {
	resetTraceStorage()

	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Check context has correlation ID
		val := r.Context().Value(CorrelationIDKey)
		require.NotNil(t, val)
		cid, ok := val.(string)
		require.True(t, ok)
		ctxID = cid
		time.Sleep(10 * time.Millisecond)
		w.WriteHeader(http.StatusCreated)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test/path", nil)

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)
	assert.Equal(t, respID, ctxID)

	// Trace should be stored
	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodGet, td.Method)
	assert.Equal(t, "/test/path", td.Path)
	assert.Equal(t, respID, td.CorrelationID)
	assert.Equal(t, http.StatusCreated, td.Status)
	assert.GreaterOrEqual(t, td.DurationMS, float64(1)) // should be at least 1ms due to sleep
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraceStorage()

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/default", nil)

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)
	respID := rr.Header().Get(CorrelationIDHeader)
	require.NotEmpty(t, respID)

	traces := GetTraces(respID)
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestCorrelationIDMiddleware_UsesExistingValidID(t *testing.T) {
	resetTraceStorage()

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/existing", nil)
	req.Header.Set(CorrelationIDHeader, "existing-1234567890")

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)

	assert.Equal(t, "existing-1234567890", rr.Header().Get(CorrelationIDHeader))

	traces := GetTraces("existing-1234567890")
	require.Len(t, traces, 1)
	assert.Equal(t, http.StatusAccepted, traces[0].Status)
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, "cid-1234567890")

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces("cid-1234567890")
	require.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodPost, td.Method)
	assert.Equal(t, "/track", td.Path)
	assert.Equal(t, http.StatusAccepted, td.Status)
	assert.NotZero(t, td.Timestamp.Unix())
}

func TestTrackRequest_DoesNothingWhenNoHeader(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)
	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestStoreTrace_ConcurrencySafety(t *testing.T) {
	resetTraceStorage()

	const (
		id    = "conc-1234567890"
		count = 100
	)
	var wg sync.WaitGroup
	wg.Add(count)
	for i := 0; i < count; i++ {
		go func() {
			defer wg.Done()
			storeTrace(id, TraceData{
				Service:       "go-parser",
				Method:        http.MethodGet,
				Path:          "/c",
				Timestamp:     time.Now(),
				CorrelationID: id,
				Status:        http.StatusOK,
			})
		}()
	}
	wg.Wait()

	traces := GetTraces(id)
	assert.Len(t, traces, count)
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage()

	oldID := "old-1234567890"
	newID := "new-1234567890"

	// Prepopulate with one old and one new entry
	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: oldID},
	}
	traceStorage[newID] = []TraceData{
		{Timestamp: time.Now(), CorrelationID: newID},
	}
	traceMutex.Unlock()

	// Trigger cleanup via storeTrace
	storeTrace("trigger-1234567890", TraceData{
		Timestamp:     time.Now(),
		CorrelationID: "trigger-1234567890",
	})

	all := GetAllTraces()
	_, oldExists := all[oldID]
	_, newExists := all[newID]
	assert.False(t, oldExists, "old traces should be removed")
	assert.True(t, newExists, "new traces should remain")
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()

	id := "copy-1234567890"
	storeTrace(id, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/a",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        201,
	})
	storeTrace(id, TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/b",
		Timestamp:     time.Now(),
		CorrelationID: id,
		Status:        202,
	})

	tr := GetTraces(id)
	require.Len(t, tr, 2)
	tr[0].Status = 500

	tr2 := GetTraces(id)
	require.Len(t, tr2, 2)
	assert.Equal(t, 201, tr2[0].Status)
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()

	a := "a-1234567890"
	b := "b-1234567890"
	storeTrace(a, TraceData{CorrelationID: a, Timestamp: time.Now(), Status: 200})
	storeTrace(b, TraceData{CorrelationID: b, Timestamp: time.Now(), Status: 201})

	all := GetAllTraces()
	require.Len(t, all, 2)

	// Mutate returned data
	all[a][0].Status = 999

	// Ensure internal store unaffected
	trA := GetTraces(a)
	require.Len(t, trA, 1)
	assert.Equal(t, 200, trA[0].Status)
}
