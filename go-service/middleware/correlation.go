package middleware

import (
	"context"
	"fmt"
	"net/http"
	"regexp"
	"sync"
	"time"
)

const (
	CorrelationIDHeader = "X-Correlation-ID"
	CorrelationIDKey    = "correlationID"
)

type TraceData struct {
	Service       string    `json:"service"`
	Method        string    `json:"method"`
	Path          string    `json:"path"`
	Timestamp     time.Time `json:"timestamp"`
	CorrelationID string    `json:"correlation_id"`
	DurationMS    float64   `json:"duration_ms,omitempty"`
	Status        int       `json:"status,omitempty"`
	Error         string    `json:"error,omitempty"`
}

var (
	traceStorage = make(map[string][]TraceData)
	traceMutex   sync.RWMutex
	validIDRegex = regexp.MustCompile(`^[\w\-]+$`)
)

func CorrelationIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		correlationID := extractOrGenerateCorrelationID(r)

		ctx := context.WithValue(r.Context(), CorrelationIDKey, correlationID)
		r = r.WithContext(ctx)

		w.Header().Set(CorrelationIDHeader, correlationID)

		startTime := time.Now()
		traceData := TraceData{
			Service:       "go-parser",
			Method:        r.Method,
			Path:          r.URL.Path,
			Timestamp:     startTime,
			CorrelationID: correlationID,
		}

		wrapped := &responseWriter{ResponseWriter: w, statusCode: http.StatusOK}

		next.ServeHTTP(wrapped, r)

		duration := time.Since(startTime).Milliseconds()
		traceData.DurationMS = float64(duration)
		traceData.Status = wrapped.statusCode

		storeTrace(correlationID, traceData)
	})
}

func extractOrGenerateCorrelationID(r *http.Request) string {
	existingID := r.Header.Get(CorrelationIDHeader)
	if existingID != "" && isValidCorrelationID(existingID) {
		return existingID
	}
	return generateCorrelationID()
}

func ExtractOrGenerateID(r *http.Request) string {
	return extractOrGenerateCorrelationID(r)
}

func TrackRequest(r *http.Request, statusCode int) {
	correlationID := r.Header.Get(CorrelationIDHeader)
	if correlationID == "" {
		return
	}

	traceData := TraceData{
		Service:       "go-parser",
		Method:        r.Method,
		Path:          r.URL.Path,
		Timestamp:     time.Now(),
		CorrelationID: correlationID,
		Status:        statusCode,
	}

	storeTrace(correlationID, traceData)
}

func generateCorrelationID() string {
	return fmt.Sprintf("%d-go-%d", time.Now().Unix(), time.Now().UnixNano()%100000)
}

func isValidCorrelationID(id string) bool {
	if len(id) < 10 || len(id) > 100 {
		return false
	}
	return validIDRegex.MatchString(id)
}

func storeTrace(correlationID string, trace TraceData) {
	traceMutex.Lock()
	defer traceMutex.Unlock()

	traceStorage[correlationID] = append(traceStorage[correlationID], trace)
	cleanupOldTraces()
}

func cleanupOldTraces() {
	cutoffTime := time.Now().Add(-1 * time.Hour)
	for id, traces := range traceStorage {
		if len(traces) > 0 && traces[0].Timestamp.Before(cutoffTime) {
			delete(traceStorage, id)
		}
	}
}

func GetTraces(correlationID string) []TraceData {
	traceMutex.RLock()
	defer traceMutex.RUnlock()

	traces, exists := traceStorage[correlationID]
	if !exists {
		return []TraceData{}
	}

	result := make([]TraceData, len(traces))
	copy(result, traces)
	return result
}

func GetAllTraces() map[string][]TraceData {
	traceMutex.RLock()
	defer traceMutex.RUnlock()

	result := make(map[string][]TraceData)
	for k, v := range traceStorage {
		traces := make([]TraceData, len(v))
		copy(traces, v)
		result[k] = traces
	}
	return result
}

type responseWriter struct {
	http.ResponseWriter
	statusCode int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.statusCode = code
	rw.ResponseWriter.WriteHeader(code)
}
