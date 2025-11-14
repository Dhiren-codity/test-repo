package middleware

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func resetTraceStorage(t *testing.T) {
	t.Helper()
	traceMutex.Lock()
	traceStorage = make(map[string][]TraceData)
	traceMutex.Unlock()
}

func TestIsValidCorrelationID_TableDriven(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want bool
	}{
		{name: "too short", id: "short", want: false},
		{name: "invalid chars", id: "invalid!*%chars", want: false},
		{name: "valid min length", id: "abcDEFGHIJ", want: true}, // 10 chars
		{name: "valid hyphen underscore", id: "abc-DEF_123", want: true},
		{name: "too long", id: string(make([]byte, 101)), want: false},
		{name: "valid 100 chars", id: func() string {
			s := make([]byte, 100)
			for i := range s {
				s[i] = 'a'
			}
			return string(s)
		}(), want: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isValidCorrelationID(tt.id))
		})
	}
}

func TestGenerateCorrelationID_FormatAndUniqueness(t *testing.T) {
	id1 := generateCorrelationID()
	time.Sleep(time.Millisecond) // ensure time changes to reduce flake risk
	id2 := generateCorrelationID()

	assert.NotEmpty(t, id1)
	assert.NotEmpty(t, id2)
	assert.NotEqual(t, id1, id2)

	re := regexp.MustCompile(`^\d+-go-\d+$`)
	assert.True(t, re.MatchString(id1))
	assert.True(t, re.MatchString(id2))

	assert.True(t, isValidCorrelationID(id1))
	assert.True(t, isValidCorrelationID(id2))
}

func TestExtractOrGenerateCorrelationID_ValidHeader(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	valid := "valid-12345"
	r.Header.Set(CorrelationIDHeader, valid)

	got := extractOrGenerateCorrelationID(r)
	assert.Equal(t, valid, got)
}

func TestExtractOrGenerateCorrelationID_InvalidHeaderGeneratesNew(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	invalid := "short"
	r.Header.Set(CorrelationIDHeader, invalid)

	got := extractOrGenerateCorrelationID(r)
	assert.NotEqual(t, invalid, got)
	assert.True(t, isValidCorrelationID(got))
}

func TestExtractOrGenerateID_ForwardsPrivate(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set(CorrelationIDHeader, "valid-ABCDE1")
	gotPub := ExtractOrGenerateID(r)
	gotPriv := extractOrGenerateCorrelationID(r)
	assert.Equal(t, gotPriv, gotPub)
}

func TestCorrelationIDMiddleware_SetsHeaderContextAndStoresTrace(t *testing.T) {
	resetTraceStorage(t)

	var capturedCtxID interface{}
	handler := CorrelationIDMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		capturedCtxID = r.Context().Value(CorrelationIDKey)
		w.WriteHeader(http.StatusCreated)
	}))

	req := httptest.NewRequest(http.MethodGet, "/path", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()

	respID := res.Header.Get(CorrelationIDHeader)
	assert.NotEmpty(t, respID)
	assert.Equal(t, respID, capturedCtxID)

	traces := GetTraces(respID)
	assert.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodGet, td.Method)
	assert.Equal(t, "/path", td.Path)
	assert.Equal(t, http.StatusCreated, td.Status)
	assert.GreaterOrEqual(t, td.DurationMS, float64(0))
	assert.Equal(t, respID, td.CorrelationID)
}

func TestResponseWriter_WriteHeader_CapturesStatus(t *testing.T) {
	rr := httptest.NewRecorder()
	w := &responseWriter{ResponseWriter: rr, statusCode: http.StatusOK}

	w.WriteHeader(http.StatusTeapot)

	assert.Equal(t, http.StatusTeapot, w.statusCode)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

func TestTrackRequest_WithHeader_StoresTrace(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodPost, "/submit", nil)
	cid := "valid-12345"
	req.Header.Set(CorrelationIDHeader, cid)

	TrackRequest(req, http.StatusAccepted)

	traces := GetTraces(cid)
	assert.Len(t, traces, 1)
	td := traces[0]
	assert.Equal(t, "go-parser", td.Service)
	assert.Equal(t, http.MethodPost, td.Method)
	assert.Equal(t, "/submit", td.Path)
	assert.Equal(t, http.StatusAccepted, td.Status)
	assert.Equal(t, cid, td.CorrelationID)
	assert.WithinDuration(t, time.Now(), td.Timestamp, time.Second)
}

func TestTrackRequest_NoHeader_NoStore(t *testing.T) {
	resetTraceStorage(t)

	req := httptest.NewRequest(http.MethodGet, "/n/a", nil)
	TrackRequest(req, http.StatusOK)

	all := GetAllTraces()
	assert.Empty(t, all)
}

func TestStoreTrace_AppendsAndGetReturnsCopy(t *testing.T) {
	resetTraceStorage(t)

	cid := "valid-abcde"
	t1 := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: time.Now(), CorrelationID: cid, Status: 200}
	t2 := TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/b", Timestamp: time.Now().Add(10 * time.Millisecond), CorrelationID: cid, Status: 201}

	storeTrace(cid, t1)
	storeTrace(cid, t2)

	// Initial assertions
	traces := GetTraces(cid)
	assert.Len(t, traces, 2)
	assert.Equal(t, 200, traces[0].Status)
	assert.Equal(t, 201, traces[1].Status)

	// Mutate returned slice and ensure internal state not affected
	traces[0].Status = 999
	tracesAgain := GetTraces(cid)
	assert.Equal(t, 200, tracesAgain[0].Status)
}

func TestCleanupOldTraces_RemovesOldFirstTraceOnly(t *testing.T) {
	resetTraceStorage(t)

	// Store very old trace; should be cleaned immediately on storeTrace call
	oldID := "old-123456"
	oldTrace := TraceData{
		Service:       "go-parser",
		Method:        http.MethodGet,
		Path:          "/old",
		Timestamp:     time.Now().Add(-2 * time.Hour),
		CorrelationID: oldID,
		Status:        200,
	}
	storeTrace(oldID, oldTrace)
	assert.Empty(t, GetTraces(oldID))

	// Mixed traces: first is recent, second is old; should not be deleted
	mixedID := "mixed-12345"
	recent := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/recent", Timestamp: time.Now(), CorrelationID: mixedID, Status: 200}
	older := TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/older", Timestamp: time.Now().Add(-2 * time.Hour), CorrelationID: mixedID, Status: 200}
	storeTrace(mixedID, recent)
	storeTrace(mixedID, older)

	// Trigger another cleanup cycle via storing another id
	storeTrace("trigger-12345", TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/t", Timestamp: time.Now(), CorrelationID: "trigger-12345", Status: 200})

	assert.Len(t, GetTraces(mixedID), 2)
}

func TestGetAllTraces_ReturnsDeepCopy(t *testing.T) {
	resetTraceStorage(t)

	idA := "idA-12345"
	idB := "idB-12345"
	storeTrace(idA, TraceData{Service: "go-parser", Method: http.MethodGet, Path: "/a", Timestamp: time.Now(), CorrelationID: idA, Status: 200})
	storeTrace(idB, TraceData{Service: "go-parser", Method: http.MethodPost, Path: "/b", Timestamp: time.Now(), CorrelationID: idB, Status: 201})

	all := GetAllTraces()
	assert.Len(t, all, 2)

	// Mutate the returned copy
	all[idA][0].Status = 999
	delete(all, idB)

	// Fetch again and ensure internal map not affected
	all2 := GetAllTraces()
	assert.Len(t, all2, 2)
	assert.Equal(t, 200, all2[idA][0].Status)
	assert.Equal(t, 201, all2[idB][0].Status)
}
