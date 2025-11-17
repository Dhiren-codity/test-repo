package middleware

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage() {
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestIsValidCorrelationID_Table(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{"too short", "short", false},
		{"valid min length", "abcdefghij", true}, // 10 chars
		{"valid with dash and underscore", "abc-123_zz", true},
		{"invalid char", "abc$def-1234", false},
		{"too long", strings.Repeat("a", 101), false},
		{"max boundary", strings.Repeat("a", 100), true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_ValidFormat(t *testing.T) {
	id := generateCorrelationID()
	assert.True(t, isValidCorrelationID(id))
	assert.Contains(t, id, "-go-")
}

func TestExtractOrGenerateID_UsesExistingValid(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "valid-id-12345")
	id := ExtractOrGenerateID(r)
	assert.Equal(t, "valid-id-12345", id)
}

func TestExtractOrGenerateID_IgnoresInvalid_GeneratesNew(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "bad$id")
	id := ExtractOrGenerateID(r)
	assert.NotEqual(t, "bad$id", id)
	assert.True(t, isValidCorrelationID(id))
}

func TestExtractOrGenerateID_GeneratesWhenMissing(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	id := ExtractOrGenerateID(r)
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraceStorage()

	r := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(r, http.StatusOK)

	traces := GetAllTraces()
	assert.Empty(t, traces)
}

func TestTrackRequest_WithHeader_Stores(t *testing.T) {
	resetTraceStorage()

	r := httptest.NewRequest(http.MethodPost, "/track", nil)
	r.Header.Set(CorrelationIDHeader, "track-id-12345")

	TrackRequest(r, http.StatusTeapot)

	got := GetTraces("track-id-12345")
	if assert.Len(t, got, 1) {
		assert.Equal(t, "go-parser", got[0].Service)
		assert.Equal(t, http.MethodPost, got[0].Method)
		assert.Equal(t, "/track", got[0].Path)
		assert.Equal(t, http.StatusTeapot, got[0].Status)
		assert.Equal(t, "track-id-12345", got[0].CorrelationID)
	}
}

func TestCorrelationIDMiddleware_SetsHeader_Context_StoresTrace(t *testing.T) {
	resetTraceStorage()

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctxVal := r.Context().Value(CorrelationIDKey)
		assert.NotNil(t, ctxVal)
		if s, ok := ctxVal.(string); assert.True(t, ok) {
			assert.True(t, isValidCorrelationID(s))
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, "ok")
	})

	srv := httptest.NewServer(CorrelationIDMiddleware(handler))
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/hello", nil)
	req.Header.Set(CorrelationIDHeader, "incoming-valid-12345")

	res, err := http.DefaultClient.Do(req)
	assert.NoError(t, err)
	defer res.Body.Close()

	assert.Equal(t, http.StatusCreated, res.StatusCode)
	assert.Equal(t, "incoming-valid-12345", res.Header.Get(CorrelationIDHeader))

	traces := GetTraces("incoming-valid-12345")
	if assert.Len(t, traces, 1) {
		td := traces[0]
		assert.Equal(t, "go-parser", td.Service)
		assert.Equal(t, http.MethodGet, td.Method)
		assert.Equal(t, "/hello", td.Path)
		assert.Equal(t, "incoming-valid-12345", td.CorrelationID)
		assert.Equal(t, http.StatusCreated, td.Status)
		assert.True(t, td.DurationMS >= 0)
	}
}

func TestCorrelationIDMiddleware_GeneratesWhenIncomingInvalid(t *testing.T) {
	resetTraceStorage()

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	srv := httptest.NewServer(CorrelationIDMiddleware(handler))
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/path", nil)
	req.Header.Set(CorrelationIDHeader, "bad$id")

	res, err := http.DefaultClient.Do(req)
	assert.NoError(t, err)
	defer res.Body.Close()

	genID := res.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, genID)
	assert.NotEqual(t, "bad$id", genID)
	assert.True(t, isValidCorrelationID(genID))

	traces := GetTraces(genID)
	assert.Len(t, traces, 1)
	assert.Equal(t, http.StatusOK, traces[0].Status)
}

func TestCorrelationIDMiddleware_DefaultStatusWhenNoWriteHeader(t *testing.T) {
	resetTraceStorage()

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "body")
	})

	srv := httptest.NewServer(CorrelationIDMiddleware(handler))
	defer srv.Close()

	res, err := http.Get(srv.URL + "/noheader")
	assert.NoError(t, err)
	defer res.Body.Close()

	assert.Equal(t, http.StatusOK, res.StatusCode)

	all := GetAllTraces()
	// There should be exactly one correlation ID in the map; fetch the single trace
	var found TraceData
	foundAny := false
	for _, v := range all {
		if len(v) > 0 {
			found = v[0]
			foundAny = true
			break
		}
	}
	if assert.True(t, foundAny) {
		assert.Equal(t, http.StatusOK, found.Status)
		assert.Equal(t, "/noheader", found.Path)
	}
}

func TestStoreTrace_CleansUpOldTraces(t *testing.T) {
	resetTraceStorage()

	// Store an old trace; cleanup should remove it immediately
	oldTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: "old-id-12345",
		Status:        http.StatusOK,
	}
	storeTrace("old-id-12345", oldTrace)

	assert.Empty(t, GetTraces("old-id-12345"))

	// Store a fresh trace; should remain
	newTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/new",
		Timestamp:     time.Now(),
		CorrelationID: "new-id-12345",
		Status:        http.StatusOK,
	}
	storeTrace("new-id-12345", newTrace)

	got := GetTraces("new-id-12345")
	assert.Len(t, got, 1)
	assert.Equal(t, "/new", got[0].Path)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()

	trace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: "copy-id-12345",
		Status:        http.StatusOK,
	}
	storeTrace("copy-id-12345", trace)

	out1 := GetTraces("copy-id-12345")
	if assert.Len(t, out1, 1) {
		out1[0].Status = http.StatusTeapot
	}

	// Original should remain unchanged
	out2 = GetTraces("copy-id-12345")
	assert.Len(t, out2, 1)
	assert.Equal(t, http.StatusOK, out2[0].Status)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStorage()

	td := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/deep",
		Timestamp:     time.Now(),
		CorrelationID: "deep-id-12345",
		Status:        http.StatusOK,
	}
	storeTrace("deep-id-12345", td)

	all := GetAllTraces()
	if assert.Contains(t, all, "deep-id-12345") && assert.Len(t, all["deep-id-12345"], 1) {
		all["deep-id-12345"][0].Status = http.StatusTeapot
		delete(all, "deep-id-12345")
	}

	// Underlying storage should be unaffected
	got := GetTraces("deep-id-12345")
	assert.Len(t, got, 1)
	assert.Equal(t, http.StatusOK, got[0].Status)
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)

	assert.Equal(t, http.StatusTeapot, rw.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}
