package middleware

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func makeString(n int) string {
	var b strings.Builder
	b.Grow(n)
	for i := 0; i < n; i++ {
		b.WriteByte('a')
	}
	return b.String()
}

func TestValidateParseRequest_Scenarios(t *testing.T) {
	tests := []struct {
		name       string
		content    string
		path       string
		expFields  []string
		expReasons []string
	}{
		{
			name:    "valid content and path",
			content: "hello",
			path:    "dir/file",
		},
		{
			name:       "empty content",
			content:    "",
			path:       "dir/file",
			expFields:  []string{"content"},
			expReasons: []string{"Content is required and cannot be empty"},
		},
		{
			name:       "content exceeds max size",
			content:    makeString(MaxContentSize + 1),
			path:       "dir/file",
			expFields:  []string{"content"},
			expReasons: []string{"Content exceeds maximum size of 1MB"},
		},
		{
			name:       "content contains null bytes",
			content:    "ab\x00cd",
			path:       "dir/file",
			expFields:  []string{"content"},
			expReasons: []string{"Content contains invalid null bytes"},
		},
		{
			name:       "path exceeds max length",
			content:    "hello",
			path:       makeString(MaxPathLength + 1),
			expFields:  []string{"path"},
			expReasons: []string{"Path exceeds maximum length"},
		},
		{
			name:       "path has directory traversal",
			content:    "hello",
			path:       "../etc/passwd",
			expFields:  []string{"path"},
			expReasons: []string{"Path contains potential directory traversal"},
		},
		{
			name:       "multiple path issues",
			content:    "hello",
			path:       makeString(MaxPathLength+1) + "../bad",
			expFields:  []string{"path", "path"},
			expReasons: []string{"Path exceeds maximum length", "Path contains potential directory traversal"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()

			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Equal(t, len(tt.expFields), len(errs))
			for i := range errs {
				assert.Equal(t, tt.expFields[i], errs[i].Field)
				assert.Equal(t, tt.expReasons[i], errs[i].Reason)
				assert.False(t, errs[i].Time.IsZero())
				assert.WithinDuration(t, time.Now(), errs[i].Time, time.Second*5)
			}

			global := GetValidationErrors()
			assert.Equal(t, len(tt.expFields), len(global))
			for i := range global {
				assert.Equal(t, tt.expFields[i], global[i].Field)
				assert.Equal(t, tt.expReasons[i], global[i].Reason)
				assert.False(t, global[i].Time.IsZero())
			}
		})
	}
}

func TestValidateDiffRequest_Scenarios(t *testing.T) {
	tests := []struct {
		name       string
		oldC       string
		newC       string
		expFields  []string
		expReasons []string
	}{
		{
			name:       "both empty",
			oldC:       "",
			newC:       "",
			expFields:  []string{"old_content", "new_content"},
			expReasons: []string{"Old content is required", "New content is required"},
		},
		{
			name:       "old too big, new ok",
			oldC:       makeString(MaxContentSize + 1),
			newC:       "ok",
			expFields:  []string{"old_content"},
			expReasons: []string{"Old content exceeds maximum size"},
		},
		{
			name:       "new too big, old ok",
			oldC:       "ok",
			newC:       makeString(MaxContentSize + 1),
			expFields:  []string{"new_content"},
			expReasons: []string{"New content exceeds maximum size"},
		},
		{
			name: "both ok",
			oldC: "old",
			newC: "new",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()

			errs := ValidateDiffRequest(tt.oldC, tt.newC)
			assert.Equal(t, len(tt.expFields), len(errs))
			for i := range errs {
				assert.Equal(t, tt.expFields[i], errs[i].Field)
				assert.Equal(t, tt.expReasons[i], errs[i].Reason)
				assert.False(t, errs[i].Time.IsZero())
			}

			global := GetValidationErrors()
			assert.Equal(t, len(tt.expFields), len(global))
		})
	}
}

func TestSanitizeInput_RemovesControlChars(t *testing.T) {
	in := "A\x00B\x01C\x02D\nE\tF\vG\fH\x0eI\x1fJ\x7fK\rL"
	out := SanitizeInput(in)
	assert.Equal(t, "ABCD\nE\tFGHIJK\rL", out)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("foo\x00bar"))
	assert.False(t, containsNullBytes("foobar"))
}

func TestSanitizeRequestBody_SanitizesKnownFields(t *testing.T) {
	body := `{
		"content":"A\u0000B\n\t",
		"path":"..\u0000/secret",
		"old_content":"\u0001x",
		"new_content":"y\u007f"
	}`
	req := httptest.NewRequest(http.MethodPost, "/sanitize", strings.NewReader(body))
	SanitizeRequestBody(req)

	// Read sanitized body
	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	var data map[string]any
	err = json.Unmarshal(b, &data)
	assert.NoError(t, err)

	// Assert sanitized strings (no nulls or 0x7f; \n and \t preserved)
	assert.Equal(t, "AB\n\t", data["content"])
	assert.Equal(t, "../secret", data["path"])
	assert.Equal(t, "x", data["old_content"])
	assert.Equal(t, "y", data["new_content"])

	// ContentLength should reflect sanitized body
	assert.Equal(t, int64(len(b)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_PassesThrough(t *testing.T) {
	orig := "{ invalid json "
	req := httptest.NewRequest(http.MethodPost, "/sanitize", strings.NewReader(orig))

	SanitizeRequestBody(req)

	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(b))
}

func TestValidationMiddleware_SanitizesOnPost(t *testing.T) {
	body := `{"content":"A\u0000B\n\t","path":"..\u0000/x","old_content":"\u0001x","new_content":"y\u007f"}`
	var capturedBody []byte
	var capturedCL string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		capturedBody = append(capturedBody, b...)
		capturedCL = strconv.FormatInt(r.ContentLength, 10)
		w.Header().Set("X-CL", capturedCL)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	h := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/mw", strings.NewReader(body))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	res := rr.Result()
	defer res.Body.Close()

	respBody, _ := io.ReadAll(res.Body)

	// The body seen by the next handler should be sanitized JSON
	var data map[string]any
	assert.NoError(t, json.Unmarshal(respBody, &data))
	assert.Equal(t, "AB\n\t", data["content"])
	assert.Equal(t, "../x", data["path"])
	assert.Equal(t, "x", data["old_content"])
	assert.Equal(t, "y", data["new_content"])

	// Content-Length passed to handler should match sanitized size
	assert.Equal(t, strconv.Itoa(len(capturedBody)), capturedCL)
	assert.Equal(t, strconv.Itoa(len(capturedBody)), res.Header.Get("X-CL"))
}

func TestValidationMiddleware_NonPost_DoesNotSanitize(t *testing.T) {
	// Include escaped null which would be removed if sanitized; ensure body is unchanged.
	body := `{"content":"A\u0000B"}`
	var seen string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen = string(b)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	h := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/mw", strings.NewReader(body))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	assert.Equal(t, body, seen)
	assert.Equal(t, body, rr.Body.String())
}

func TestValidationMiddleware_InvalidJSON_PassesThrough(t *testing.T) {
	body := "{ invalid "
	var seen string

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen = string(b)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	h := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/mw", strings.NewReader(body))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	assert.Equal(t, body, seen)
	assert.Equal(t, body, rr.Body.String())
}

func TestGetAndClearValidationErrors_CopyAndTruncate(t *testing.T) {
	ClearValidationErrors()

	// Log 120 errors, expect stored only last 100
	var errs []ValidationError
	for i := 0; i < 120; i++ {
		errs = append(errs, ValidationError{
			Field:  "e" + strconv.Itoa(i),
			Reason: "r" + strconv.Itoa(i),
			Time:   time.Now(),
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "e20", got[0].Field)
	assert.Equal(t, "e119", got[len(got)-1].Field)

	// Mutation of returned slice should not affect internal storage
	got[0].Field = "mutated"
	gotAgain := GetValidationErrors()
	assert.Equal(t, "e20", gotAgain[0].Field)

	// Clear should empty
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestSanitizeRequestBody_NoTargetFields(t *testing.T) {
	// Ensure it does not panic and ContentLength is consistent even if no known fields present
	body := `{"other":"value\u0000","num":1}`
	req := httptest.NewRequest(http.MethodPost, "/sanitize", strings.NewReader(body))

	SanitizeRequestBody(req)

	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(b)), req.ContentLength)

	// The "other" field is not sanitized by design; it remains with the original value when unmarshaled
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	if v, ok := m["other"].(string); ok {
		// original value was "value\u0000"; after unmarshal/marshal roundtrip, it remains the same
		assert.Equal(t, "value\u0000", v)
	}
}

func TestValidationErrors_IsolatedPerCall(t *testing.T) {
	// Ensure logging multiple times appends and truncates properly
	ClearValidationErrors()

	logValidationErrors([]ValidationError{{Field: "a", Reason: "ra", Time: time.Now()}})
	logValidationErrors([]ValidationError{{Field: "b", Reason: "rb", Time: time.Now()}})

	got := GetValidationErrors()
	assert.Len(t, got, 2)
	assert.Equal(t, "a", got[0].Field)
	assert.Equal(t, "b", got[1].Field)
}
