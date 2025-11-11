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

func TestValidateParseRequest_ContentValidation(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name       string
		content    string
		wantField  string
		wantReason string
	}{
		{
			name:       "empty content",
			content:    "",
			wantField:  "content",
			wantReason: "Content is required and cannot be empty",
		},
		{
			name:       "content too large",
			content:    strings.Repeat("a", MaxContentSize+1),
			wantField:  "content",
			wantReason: "Content exceeds maximum size of 1MB",
		},
		{
			name:       "content contains null bytes",
			content:    "abc\x00def",
			wantField:  "content",
			wantReason: "Content contains invalid null bytes",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, "")
			assert.NotEmpty(t, errs)
			assert.Equal(t, tt.wantField, errs[0].Field)
			assert.Equal(t, tt.wantReason, errs[0].Reason)

			logged := GetValidationErrors()
			assert.Equal(t, len(errs), len(logged))
			assert.Equal(t, tt.wantField, logged[0].Field)
			assert.Equal(t, tt.wantReason, logged[0].Reason)
		})
	}
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	ClearValidationErrors()

	// Path length exceeded
	longPath := strings.Repeat("x", MaxPathLength+1)
	errs := ValidateParseRequest("ok", longPath)
	assert.NotEmpty(t, errs)
	assert.Equal(t, "path", errs[0].Field)
	assert.Equal(t, "Path exceeds maximum length", errs[0].Reason)

	// Directory traversal with ".."
	ClearValidationErrors()
	errs = ValidateParseRequest("ok", "a/../b")
	assert.NotEmpty(t, errs)
	assert.Equal(t, "path", errs[0].Field)
	assert.Equal(t, "Path contains potential directory traversal", errs[0].Reason)

	// Directory traversal with "~/"
	ClearValidationErrors()
	errs = ValidateParseRequest("ok", "~/secrets")
	assert.NotEmpty(t, errs)
	assert.Equal(t, "path", errs[0].Field)
	assert.Equal(t, "Path contains potential directory traversal", errs[0].Reason)
}

func TestValidateDiffRequest_Validation(t *testing.T) {
	ClearValidationErrors()

	// Both empty
	errs := ValidateDiffRequest("", "")
	assert.Len(t, errs, 2)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Equal(t, "Old content is required", errs[0].Reason)
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Equal(t, "New content is required", errs[1].Reason)

	// Size exceeded
	ClearValidationErrors()
	tooBig := strings.Repeat("a", MaxContentSize+1)
	errs = ValidateDiffRequest(tooBig, tooBig)
	assert.Len(t, errs, 2)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Equal(t, "Old content exceeds maximum size", errs[0].Reason)
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Equal(t, "New content exceeds maximum size", errs[1].Reason)

	// Mixed: old ok, new empty
	ClearValidationErrors()
	errs = ValidateDiffRequest("old", "")
	assert.Len(t, errs, 1)
	assert.Equal(t, "new_content", errs[0].Field)
	assert.Equal(t, "New content is required", errs[0].Reason)
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	in := "Hello\u0000World\u0007!\nKeep\rThis\tHere\u000B\u000C\u001E\u007F\u009F"
	out := SanitizeInput(in)
	assert.Equal(t, "HelloWorld!\nKeep\rThis\tHere", out)
}

func TestSanitizeRequestBody_SanitizesJSONFields(t *testing.T) {
	// Use escaped unicode to ensure JSON is valid; these will decode to control chars.
	body := []byte(`{
		"content":"Hi\\u0000There",
		"path":"abc\\u0007def",
		"old_content":"Old\\u001E",
		"new_content":"New\\u007F"
	}`)
	req := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(body))

	SanitizeRequestBody(req)

	after, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(after)), req.ContentLength)

	var m map[string]string
	err = json.Unmarshal(after, &m)
	assert.NoError(t, err)

	assert.Equal(t, "HiThere", m["content"])
	assert.Equal(t, "abcdef", m["path"])
	assert.Equal(t, "Old", m["old_content"])
	assert.Equal(t, "New", m["new_content"])
}

func TestSanitizeRequestBody_InvalidJSON_NoChange(t *testing.T) {
	raw := []byte("not json")
	req := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(raw))

	SanitizeRequestBody(req)

	after, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, string(raw), string(after))
}

func TestValidationMiddleware_SanitizesPOSTBody(t *testing.T) {
	orig := []byte(`{
		"content":"Hi\\u0000There",
		"path":"abc\\u0007def",
		"old_content":"Old\\u001E",
		"new_content":"New\\u007F"
	}`)

	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	})

	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(orig))
	ValidationMiddleware(h).ServeHTTP(w, r)

	res := w.Result()
	defer res.Body.Close()
	assert.Equal(t, http.StatusOK, res.StatusCode)

	decoded := map[string]string{}
	respBytes, _ := io.ReadAll(res.Body)
	err := json.Unmarshal(respBytes, &decoded)
	assert.NoError(t, err)
	assert.Equal(t, "HiThere", decoded["content"])
	assert.Equal(t, "abcdef", decoded["path"])
	assert.Equal(t, "Old", decoded["old_content"])
	assert.Equal(t, "New", decoded["new_content"])
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	orig := []byte(`{"content":"Hi\\u0000There"}`)
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	})

	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/x", bytes.NewReader(orig))
	ValidationMiddleware(h).ServeHTTP(w, r)

	res := w.Result()
	defer res.Body.Close()
	out, _ := io.ReadAll(res.Body)
	assert.Equal(t, http.StatusOK, res.StatusCode)
	// Should be identical, no sanitization on non-POST
	assert.Equal(t, string(orig), string(out))
}

func TestValidationMiddleware_InvalidJSON_PassThrough(t *testing.T) {
	orig := []byte(`{"content":"Hi\\u0000There"`) // invalid JSON (missing closing brace)
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	})

	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewReader(orig))
	ValidationMiddleware(h).ServeHTTP(w, r)

	res := w.Result()
	defer res.Body.Close()
	out, _ := io.ReadAll(res.Body)
	assert.Equal(t, http.StatusOK, res.StatusCode)
	// Middleware should pass original bytes when JSON is invalid
	assert.Equal(t, string(orig), string(out))
}

func TestGetValidationErrorsAndClear(t *testing.T) {
	ClearValidationErrors()
	// Log one error via helper
	logValidationErrors([]ValidationError{
		{Field: "a", Reason: "x"},
	})

	got := GetValidationErrors()
	assert.Len(t, got, 1)
	assert.Equal(t, "a", got[0].Field)
	assert.Equal(t, "x", got[0].Reason)

	ClearValidationErrors()
	got = GetValidationErrors()
	assert.Len(t, got, 0)
}

func TestLogValidationErrors_RingBuffer(t *testing.T) {
	ClearValidationErrors()

	var batch []ValidationError
	for i := 0; i < 120; i++ {
		batch = append(batch, ValidationError{
			Field:  "f",
			Reason: "r" + strconvI(i),
		})
	}
	logValidationErrors(batch)

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	// Should contain last 100 from indices 20..119
	assert.Equal(t, "r20", got[0].Reason)
	assert.Equal(t, "r119", got[len(got)-1].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

// helper to avoid importing strconv for a single test purpose
func strconvI(i int) string {
	digits := "0123456789"
	if i == 0 {
		return "0"
	}
	var b [20]byte
	pos := len(b)
	n := i
	for n > 0 {
		pos--
		b[pos] = digits[n%10]
		n /= 10
	}
	return string(b[pos:])
}
