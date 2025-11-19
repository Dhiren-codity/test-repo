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
		{"valid typical", "valid-abcde_12345", true},
		{"valid boundary length 10", "abcdefghij", true},
		{"valid boundary length 100", func() string {
			s := make([]byte, 100)
			for i := range s {
				s[i] = 'a'
			}
			return string(s)
		}(), true},
		{"too short (<10)", "short-id", false},
		{"too long (>100)", func() string {
			s := make([]byte, 101)
			for i := range s {
				s[i] = 'a'
			}
			return string(s)
		}(), false},
		{"invalid chars (space)", "invalid id", false},
		{"invalid chars (!)", "invalid!id", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isValidCorrelationID(tt.id)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestExtractOrGenerateID_UsesExistingValidID(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	existing := "valid-header_12345"
	req.Header.Set(CorrelationIDHeader, existing)
	id := ExtractOrGenerateID(req)
	assert.Equal(t, existing, id)
}

func TestExtractOrGenerateID_GeneratesWhenMissingOrInvalid(t *testing.T) {
	// Missing header
	req1 := httptest.NewRequest(http.MethodGet, "/test", nil)
	id1 := ExtractOrGenerateID(req1)
	assert.NotEmpty(t, id1)
	assert.True(t, isValidCorrelationID(id1))

	// Invalid header present
	req2 := httptest.NewRequest(http.MethodGet, "/test", nil)
	req2.Header.Set(CorrelationIDHeader, "bad id")
	id2 := ExtractOrGenerateID(req2)
	assert.NotEmpty(t, id2)
	assert.NotEqual(t, "bad id", id2)
	assert.True(t, isValidCorrelationID(id2))
}

func TestGenerateCorrelationID_IsValidFormat(t *testing.T) {
	id := generateCorrelationID()
	assert.NotEmpty(t, id)
	assert.True(t, isValidCorrelationID(id))

	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.True(t, re.MatchString(id))
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusCreated)
	assert.Equal(t, http.StatusCreated, rw.statusCode)
	assert.Equal(t, http.StatusCreated, rr.Code)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_WithExplicitStatus(t *testing.T) {
	resetTraces()

	var gotCtxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		val := r.Context().Value(CorrelationIDKey)
		if val != nil {
			if s, ok := val.(string); ok {
				gotCtxID = s
			}
		}
		w.WriteHeader(http.StatusTeapot)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/path", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	cid := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, cid)
	assert.Equal(t, gotCtxID, cid)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		tr := traces[0]
		assert.Equal(t, "go-parser", tr.Service)
		assert.Equal(t, http.MethodGet, tr.Method)
		assert.Equal(t, "/path", tr.Path)
		assert.Equal(t, cid, tr.CorrelationID)
		assert.Equal(t, http.StatusTeapot, tr.Status)
		assert.GreaterOrEqual(t, tr.DurationMS, float64(0))
		assert.False(t, tr.Timestamp.IsZero())
	}
}

func TestCorrelationIDMiddleware_DefaultsStatusTo200WhenNoWriteHeader(t *testing.T) {
	resetTraces()

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "hello")
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	cid := rr.Header().Get(CorrelationIDHeader)
	assert.NotEmpty(t, cid)
	assert.Equal(t, http.StatusOK, rr.Code)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, http.StatusOK, traces[0].Status)
	}
}

func TestCorrelationIDMiddleware_UsesExistingHeaderWhenValid(t *testing.T) {
	resetTraces()

	existing := "existing-valid_12345"
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/keep", nil)
	req.Header.Set(CorrelationIDHeader, existing)

	CorrelationIDMiddleware(h).ServeHTTP(rr, req)

	assert.Equal(t, existing, rr.Header().Get(CorrelationIDHeader))
	traces := GetTraces(existing)
	if assert.Len(t, traces, 1) {
		assert.Equal(t, existing, traces[0].CorrelationID)
		assert.Equal(t, http.StatusAccepted, traces[0].Status)
	}
}

func TestTrackRequest_StoresWithHeader(t *testing.T) {
	resetTraces()

	cid := "track-valid_12345"
	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces(cid)
	if assert.Len(t, traces, 1) {
		tr := traces[0]
		assert.Equal(t, "go-parser", tr.Service)
		assert.Equal(t, http.MethodPost, tr.Method)
		assert.Equal(t, "/track", tr.Path)
		assert.Equal(t, cid, tr.CorrelationID)
		assert.Equal(t, http.StatusAccepted, tr.Status)
		assert.False(t, tr.Timestamp.IsZero())
	}
}

func TestTrackRequest_SkipsWhenHeaderMissing(t *testing.T) {
	resetTraces()

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Len(t, all, 0)
}

func TestGetTraces_ReturnsCopy(t *testing.T) {
	resetTraces()

	cid := "copy-test_12345"
	orig := TraceData{
		Service:       "orig",
		Method:        http.MethodGet,
		Path:          "/copy",
		Timestamp:     time.Now(),
		CorrelationID: cid,
		Status:        http.StatusOK,
	}
	storeTrace(cid, orig)

	out := GetTraces(cid)
	if assert.Len(t, out, 1) {
		out[0].Service = "mutated"
	}

	out2 := GetTraces(cid)
	if assert.Len(t, out2, 1) {
		assert.Equal(t, "orig", out2[0].Service)
	}
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraces()

	cid1 := "cid1_valid_12345"
	cid2 := "cid2_valid_12345"
	storeTrace(cid1, TraceData{Service: "s1", Timestamp: time.Now()})
	storeTrace(cid2, TraceData{Service: "s2", Timestamp: time.Now()})

	all := GetAllTraces()
	assert.Contains(t, all, cid1)
	assert.Contains(t, all, cid2)

	// mutate returned copy
	all[cid1][0].Service = "mutated"
	all[cid2] = append(all[cid2], TraceData{Service: "x"})

	// original should remain unchanged
	all2 := GetAllTraces()
	if assert.Len(t, all2[cid1], 1) {
		assert.Equal(t, "s1", all2[cid1][0].Service)
	}
	assert.Len(t, all2[cid2], 1)
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraces()

	now := time.Now()
	oldID := "old-valid_12345"
	newID := "new-valid_12345"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{{Timestamp: now.Add(-2 * time.Hour)}}
	traceStorage[newID] = []TraceData{{Timestamp: now}}
	cleanupOldTraces()
	_, oldExists := traceStorage[oldID]
	_, newExists := traceStorage[newID]
	traceMutex.Unlock()

	assert.False(t, oldExists)
	assert.True(t, newExists)
}
