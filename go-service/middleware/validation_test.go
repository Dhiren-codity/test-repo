package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		path        string
		wantReasons []string
		wantFields  []string
	}{
		{
			name:        "empty content",
			content:     "",
			path:        "",
			wantReasons: []string{"Content is required and cannot be empty"},
			wantFields:  []string{"content"},
		},
		{
			name:        "oversized content",
			content:     strings.Repeat("x", MaxContentSize+1),
			path:        "/ok",
			wantReasons: []string{"Content exceeds maximum size of 1MB"},
			wantFields:  []string{"content"},
		},
		{
			name:        "null byte in content",
			content:     "abc\x00def",
			path:        "/ok",
			wantReasons: []string{"Content contains invalid null bytes"},
			wantFields:  []string{"content"},
		},
		{
			name:        "path too long",
			content:     "ok",
			path:        strings.Repeat("a", MaxPathLength+1),
			wantReasons: []string{"Path exceeds maximum length"},
			wantFields:  []string{"path"},
		},
		{
			name:        "path traversal",
			content:     "ok",
			path:        "../etc/passwd",
			wantReasons: []string{"Path contains potential directory traversal"},
			wantFields:  []string{"path"},
		},
		{
			name:        "path traversal tilde",
			content:     "ok",
			path:        "~/secrets",
			wantReasons: []string{"Path contains potential directory traversal"},
			wantFields:  []string{"path"},
		},
		{
			name:        "multiple path errors",
			content:     "ok",
			path:        strings.Repeat("a", MaxPathLength+1) + "..",
			wantReasons: []string{"Path exceeds maximum length", "Path contains potential directory traversal"},
			wantFields:  []string{"path", "path"},
		},
		{
			name:        "no errors",
			content:     "hello",
			path:        "/safe/path",
			wantReasons: nil,
			wantFields:  nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, tt.path)
			if len(tt.wantReasons) == 0 {
				assert.Empty(t, errs)
			} else {
				assert.Len(t, errs, len(tt.wantReasons))
				var gotReasons []string
				var gotFields []string
				for _, e := range errs {
					gotReasons = append(gotReasons, e.Reason)
					gotFields = append(gotFields, e.Field)
				}
				for _, r := range tt.wantReasons {
					assert.Contains(t, gotReasons, r)
				}
				for _, f := range tt.wantFields {
					assert.Contains(t, gotFields, f)
				}
			}

			// Ensure errors were logged globally
			logged := GetValidationErrors()
			assert.Equal(t, len(errs), len(logged))
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	tests := []struct {
		name        string
		oldContent  string
		newContent  string
		wantReasons []string
		wantFields  []string
	}{
		{
			name:        "missing old content",
			oldContent:  "",
			newContent:  "new",
			wantReasons: []string{"Old content is required"},
			wantFields:  []string{"old_content"},
		},
		{
			name:        "missing new content",
			oldContent:  "old",
			newContent:  "",
			wantReasons: []string{"New content is required"},
			wantFields:  []string{"new_content"},
		},
		{
			name:        "both oversized",
			oldContent:  strings.Repeat("o", MaxContentSize+1),
			newContent:  strings.Repeat("n", MaxContentSize+1),
			wantReasons: []string{"Old content exceeds maximum size", "New content exceeds maximum size"},
			wantFields:  []string{"old_content", "new_content"},
		},
		{
			name:        "ok",
			oldContent:  "old",
			newContent:  "new",
			wantReasons: nil,
			wantFields:  nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			if len(tt.wantReasons) == 0 {
				assert.Empty(t, errs)
			} else {
				assert.Len(t, errs, len(tt.wantReasons))
				var gotReasons []string
				var gotFields []string
				for _, e := range errs {
					gotReasons = append(gotReasons, e.Reason)
					gotFields = append(gotFields, e.Field)
				}
				for _, r := range tt.wantReasons {
					assert.Contains(t, gotReasons, r)
				}
				for _, f := range tt.wantFields {
					assert.Contains(t, gotFields, f)
				}
			}

			// Ensure errors were logged globally
			logged := GetValidationErrors()
			assert.Equal(t, len(errs), len(logged))
		})
	}
}

func TestSanitizeInput(t *testing.T) {
	tests := []struct {
		name string
		in   string
		out  string
	}{
		{
			name: "remove null byte",
			in:   "a\x00b",
			out:  "ab",
		},
		{
			name: "preserve newline and tab and carriage return",
			in:   "a\nb\tc\rd",
			out:  "a\nb\tc\rd",
		},
		{
			name: "remove bell and vertical tab and DEL",
			in:   "x\x07y\x0bz\x7Fq",
			out:  "xyzq",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := SanitizeInput(tt.in)
			assert.Equal(t, tt.out, got)
		})
	}
}

func TestSanitizeRequestBody_ValidJSON(t *testing.T) {
	bodyMap := map[string]interface{}{
		"content":     "a\x00b\nc",
		"path":        "p\x07q",
		"old_content": "ol\x0bd",
		"new_content": "n\x1few",
	}
	raw, err := json.Marshal(bodyMap)
	assert.NoError(t, err)

	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBuffer(raw))
	SanitizeRequestBody(req)

	// Read back sanitized body
	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	var got map[string]interface{}
	err = json.Unmarshal(b, &got)
	assert.NoError(t, err)

	assert.Equal(t, "ab\nc", got["content"])
	assert.Equal(t, "pq", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])

	assert.Equal(t, int64(len(b)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON(t *testing.T) {
	orig := []byte("not-json")
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBuffer(orig))
	SanitizeRequestBody(req)

	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, string(orig), string(b))
}

func TestValidationMiddleware_POST_Sanitizes(t *testing.T) {
	// next handler echoes sanitized body and records content length consistency
	var observedBodyLen int
	var observedContentLength int64

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		observedBodyLen = len(body)
		observedContentLength = r.ContentLength
		w.Write(body)
	})

	h := ValidationMiddleware(next)

	bodyMap := map[string]interface{}{
		"content":     "a\x00b\nc",
		"path":        "p\x07q",
		"old_content": "ol\x0bd",
		"new_content": "n\x1few",
	}
	raw, _ := json.Marshal(bodyMap)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBuffer(raw))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	respBody := rr.Body.Bytes()
	var got map[string]interface{}
	err := json.Unmarshal(respBody, &got)
	assert.NoError(t, err)
	assert.Equal(t, "ab\nc", got["content"])
	assert.Equal(t, "pq", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])

	assert.Equal(t, int64(observedBodyLen), observedContentLength)
}

func TestValidationMiddleware_POST_InvalidJSON_Passthrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Write(body)
	})

	h := ValidationMiddleware(next)

	orig := []byte("not-json")
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBuffer(orig))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	assert.Equal(t, string(orig), rr.Body.String())
}

func TestValidationMiddleware_NonPOST_NoSanitize(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Write(body)
	})

	h := ValidationMiddleware(next)

	orig := []byte("abc\x07def")
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBuffer(orig))
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	assert.Equal(t, string(orig), rr.Body.String())
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}

func TestLogValidationErrors_Trimming(t *testing.T) {
	ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 150; i++ {
		errs = append(errs, ValidationError{
			Field:  "field",
			Reason: "err-" + strconvI(i),
		})
	}
	logValidationErrors(errs)

	logged := GetValidationErrors()
	assert.Equal(t, 100, len(logged))
	assert.Equal(t, "err-50", logged[0].Reason)
	assert.Equal(t, "err-149", logged[len(logged)-1].Reason)
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	logValidationErrors([]ValidationError{
		{Field: "a", Reason: "b"},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 1)

	ClearValidationErrors()
	errs = GetValidationErrors()
	assert.Empty(t, errs)
}

// helper: int to string without importing strconv in tests
func strconvI(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	var b []byte
	n := i
	for n > 0 {
		b = append(b, digits[n%10])
		n /= 10
	}
	// reverse
	for l, r := 0, len(b)-1; l < r; l, r = l+1, r-1 {
		b[l], b[r] = b[r], b[l]
	}
	return string(b)
}
