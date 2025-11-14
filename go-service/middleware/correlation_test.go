package middleware

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
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
			if got != tt.want {
				t.Fatalf("isValidCorrelationID(%q) = %v, want %v", tt.id, got, tt.want)
			}
		})
	}
}

func TestGenerateCorrelationID_IsValid(t *testing.T) {
	id := generateCorrelationID()
	if id == "" {
		t.Fatal("generated correlation ID should not be empty")
	}
	if !isValidCorrelationID(id) {
		t.Fatalf("generated correlation ID should be valid, got %q", id)
	}
}

func TestExtractOrGenerateCorrelationID(t *testing.T) {
	t.Run("uses existing valid header", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set(CorrelationIDHeader, "valid-1234567890")
		got := extractOrGenerateCorrelationID(r)
		if got != "valid-1234567890" {
			t.Fatalf("extractOrGenerateCorrelationID did not use existing header, got %q", got)
		}
	})

	t.Run("generates when missing", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		got := extractOrGenerateCorrelationID(r)
		if got == "" {
			t.Fatal("should generate correlation ID when missing")
		}
	})

	t.Run("generates when invalid", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set(CorrelationIDHeader, "bad$id")
		got := extractOrGenerateCorrelationID(r)
		if got == "bad$id" {
			t.Fatal("should not return invalid header value")
		}
		if !isValidCorrelationID(got) {
			t.Fatalf("generated ID should be valid, got %q", got)
		}
	})
}

func TestExtractOrGenerateID_Exported(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "valid-1234567890")
	got := ExtractOrGenerateID(r)
	if got != "valid-1234567890" {
		t.Fatalf("ExtractOrGenerateID = %q, want %q", got, "valid-1234567890")
	}
}

func TestResponseWriter_WriteHeader(t *testing.T) {
	rec := httptest.NewRecorder()
	rw := &responseWriter{ResponseWriter: rec, statusCode: http.StatusOK}

	rw.WriteHeader(http.StatusTeapot)
	if rw.statusCode != http.StatusTeapot {
		t.Fatalf("statusCode = %d, want %d", rw.statusCode, http.StatusTeapot)
	}
	if rec.Code != http.StatusTeapot {
		t.Fatalf("rec.Code = %d, want %d", rec.Code, http.StatusTeapot)
	}
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace_WithExplicitStatus(t *testing.T) {
	resetTraceStorage()

	var ctxID string
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		val := r.Context().Value(CorrelationIDKey)
		if val == nil {
			t.Fatal("context value for CorrelationIDKey should not be nil")
		}
		cid, ok := val.(string)
		if !ok {
			t.Fatal("context correlation ID should be a string")
		}
		ctxID = cid
		time.Sleep(10 * time.Millisecond)
		w.WriteHeader(http.StatusCreated)
	})

	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test/path", nil)

	mw := CorrelationIDMiddleware(h)
	mw.ServeHTTP(rr, req)

	respID := rr.Header().Get(CorrelationIDHeader)
	if respID == "" {
		t.Fatal("response should have correlation ID header")
	}
	if respID != ctxID {
		t.Fatalf("response ID %q != context ID %q", respID, ctxID)
	}

	traces := GetTraces(respID)
	if len(traces) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(traces))
	}
	td := traces[0]
	if td.Service != "go-parser" {
		t.Fatalf("Service = %q, want %q", td.Service, "go-parser")
	}
	if td.Method != http.MethodGet {
		t.Fatalf("Method = %q, want %q", td.Method, http.MethodGet)
	}
	if td.Path != "/test/path" {
		t.Fatalf("Path = %q, want %q", td.Path, "/test/path")
	}
	if td.CorrelationID != respID {
		t.Fatalf("CorrelationID = %q, want %q", td.CorrelationID, respID)
	}
	if td.Status != http.StatusCreated {
		t.Fatalf("Status = %d, want %d", td.Status, http.StatusCreated)
	}
	if !(td.DurationMS >= 1) {
		t.Fatalf("DurationMS = %f, want >= 1", td.DurationMS)
	}
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
	if respID == "" {
		t.Fatal("response should have correlation ID header")
	}

	traces := GetTraces(respID)
	if len(traces) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(traces))
	}
	if traces[0].Status != http.StatusOK {
		t.Fatalf("Status = %d, want %d", traces[0].Status, http.StatusOK)
	}
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

	if got := rr.Header().Get(CorrelationIDHeader); got != "existing-1234567890" {
		t.Fatalf("Header %s = %q, want %q", CorrelationIDHeader, got, "existing-1234567890")
	}

	traces := GetTraces("existing-1234567890")
	if len(traces) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(traces))
	}
	if traces[0].Status != http.StatusAccepted {
		t.Fatalf("Status = %d, want %d", traces[0].Status, http.StatusAccepted)
	}
}

func TestTrackRequest_StoresWhenHeaderPresent(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodPost, "/track", nil)
	req.Header.Set(CorrelationIDHeader, "cid-1234567890")

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces("cid-1234567890")
	if len(traces) != 1 {
		t.Fatalf("expected 1 trace, got %d", len(traces))
	}
	td := traces[0]
	if td.Service != "go-parser" {
		t.Fatalf("Service = %q, want %q", td.Service, "go-parser")
	}
	if td.Method != http.MethodPost {
		t.Fatalf("Method = %q, want %q", td.Method, http.MethodPost)
	}
	if td.Path != "/track" {
		t.Fatalf("Path = %q, want %q", td.Path, "/track")
	}
	if td.Status != http.StatusAccepted {
		t.Fatalf("Status = %d, want %d", td.Status, http.StatusAccepted)
	}
	if td.Timestamp.Unix() == 0 {
		t.Fatalf("Timestamp should be set")
	}
}

func TestTrackRequest_DoesNothingWhenNoHeader(t *testing.T) {
	resetTraceStorage()

	req := httptest.NewRequest(http.MethodGet, "/noheader", nil)
	TrackRequest(req, http.StatusOK)
	all := GetAllTraces()
	if len(all) != 0 {
		t.Fatalf("expected no traces, got %d", len(all))
	}
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
	if len(traces) != count {
		t.Fatalf("expected %d traces, got %d", count, len(traces))
	}
}

func TestCleanupOldTraces_RemovesOldEntries(t *testing.T) {
	resetTraceStorage()

	oldID := "old-1234567890"
	newID := "new-1234567890"

	traceMutex.Lock()
	traceStorage[oldID] = []TraceData{
		{Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: oldID},
	}
	traceStorage[newID] = []TraceData{
		{Timestamp: time.Now(), CorrelationID: newID},
	}
	traceMutex.Unlock()

	storeTrace("trigger-1234567890", TraceData{
		Timestamp:     time.Now(),
		CorrelationID: "trigger-1234567890",
	})

	all := GetAllTraces()
	_, oldExists := all[oldID]
	_, newExists := all[newID]
	if oldExists {
		t.Fatal("old traces should be removed")
	}
	if !newExists {
		t.Fatal("new traces should remain")
	}
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
	if len(tr) != 2 {
		t.Fatalf("expected 2 traces, got %d", len(tr))
	}
	tr[0].Status = 500

	tr2 := GetTraces(id)
	if len(tr2) != 2 {
		t.Fatalf("expected 2 traces, got %d", len(tr2))
	}
	if tr2[0].Status != 201 {
		t.Fatalf("internal storage mutated, got status %d want %d", tr2[0].Status, 201)
	}
}

func TestGetAllTraces_ReturnsCopy(t *testing.T) {
	resetTraceStorage()

	a := "a-1234567890"
	b := "b-1234567890"
	storeTrace(a, TraceData{CorrelationID: a, Timestamp: time.Now(), Status: 200})
	storeTrace(b, TraceData{CorrelationID: b, Timestamp: time.Now(), Status: 201})

	all := GetAllTraces()
	if len(all) != 2 {
		t.Fatalf("expected 2 ids, got %d", len(all))
	}

	all[a][0].Status = 999

	trA := GetTraces(a)
	if len(trA) != 1 {
		t.Fatalf("expected 1 trace for %s, got %d", a, len(trA))
	}
	if trA[0].Status != 200 {
		t.Fatalf("internal storage mutated, got status %d want %d", trA[0].Status, 200)
	}
}
