package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest_ContentValidation(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	tests := []struct {
		name       string
		content    string
		path       string
		wantFields []string
		wantReason []string
	}{
		{
			name:       "empty content",
			content:    "",
			path:       "",
			wantFields: []string{"content"},
			wantReason: []string{"Content is required and cannot be empty"},
		},
		{
			name:       "content too large",
			content:    strings.Repeat("a", MaxContentSize+1),
			path:       "",
			wantFields: []string{"content"},
			wantReason: []string{"Content exceeds maximum size of 1MB"},
		},
		{
			name:       "content contains null byte",
			content:    "abc\x00def",
			path:       "",
			wantFields: []string{"content"},
			wantReason: []string{"Content contains invalid null bytes"},
		},
		{
			name:       "valid content no errors",
			content:    "hello world",
			path:       "",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if tt.wantFields == nil {
				assert.Empty(t, errs)
			} else {
				assert.Len(t, errs, len(tt.wantFields))
				for i := range tt.wantFields {
					assert.Equal(t, tt.wantFields[i], errs[i].Field)
					assert.Equal(t, tt.wantReason[i], errs[i].Reason)
					assert.WithinDuration(t, time.Now(), errs[i].Time, time.Second)
				}
			}
		})
	}
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	tests := []struct {
		name       string
		content    string
		path       string
		wantFields []string
		wantReason []string
	}{
		{
			name:       "path too long",
			content:    "ok",
			path:       strings.Repeat("x", MaxPathLength+1),
			wantFields: []string{"path"},
			wantReason: []string{"Path exceeds maximum length"},
		},
		{
			name:       "path contains .. traversal",
			content:    "ok",
			path:       "../etc/passwd",
			wantFields: []string{"path"},
			wantReason: []string{"Path contains potential directory traversal"},
		},
		{
			name:       "path contains tilde traversal",
			content:    "ok",
			path:       "~/secret",
			wantFields: []string{"path"},
			wantReason: []string{"Path contains potential directory traversal"},
		},
		{
			name:       "valid path",
			content:    "ok",
			path:       "/safe/path",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if tt.wantFields == nil {
				assert.Empty(t, errs)
			} else {
				assert.Len(t, errs, len(tt.wantFields))
				for i := range tt.wantFields {
					assert.Equal(t, tt.wantFields[i], errs[i].Field)
					assert.Equal(t, tt.wantReason[i], errs[i].Reason)
				}
			}
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	tests := []struct {
		name       string
		oldContent string
		newContent string
		wantFields []string
		wantReason []string
	}{
		{
			name:       "both empty",
			oldContent: "",
			newContent: "",
			wantFields: []string{"old_content", "new_content"},
			wantReason: []string{"Old content is required", "New content is required"},
		},
		{
			name:       "old too big",
			oldContent: strings.Repeat("o", MaxContentSize+1),
			newContent: "ok",
			wantFields: []string{"old_content"},
			wantReason: []string{"Old content exceeds maximum size"},
		},
		{
			name:       "new too big",
			oldContent: "ok",
			newContent: strings.Repeat("n", MaxContentSize+1),
			wantFields: []string{"new_content"},
			wantReason: []string{"New content exceeds maximum size"},
		},
		{
			name:       "valid both",
			oldContent: "old",
			newContent: "new",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			if tt.wantFields == nil {
				assert.Empty(t, errs)
			} else {
				assert.Len(t, errs, len(tt.wantFields))
				for i := range tt.wantFields {
					assert.Equal(t, tt.wantFields[i], errs[i].Field)
					assert.Equal(t, tt.wantReason[i], errs[i].Reason)
				}
			}
		})
	}
}

func TestSanitizeInput_RemovesInvalidControls_PreservesAllowed(t *testing.T) {
	input := "Hello\x00World" + string(rune(11)) + "!" + "\n" + "\t" + "\r" + string(rune(14)) + string(rune(127))
	got := SanitizeInput(input)
	// Expected to remove: NUL(0), VT(11), 14, 127; keep \n, \t, \r
	assert.Equal(t, "HelloWorld!\n\t\r", got)
}

func TestSanitizeRequestBody_JSONSanitized(t *testing.T) {
	orig := map[string]interface{}{
		"content":     "Hi\x00there" + string(rune(11)) + "\n",
		"path":        "/ok" + string(rune(14)),
		"old_content": "old\x00",
		"new_content": "new" + string(rune(127)),
	}
	body, _ := json.Marshal(orig)
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))

	SanitizeRequestBody(r)

	// Read back body and verify fields are sanitized
	dataBytes, _ := io.ReadAll(r.Body)
	var got map[string]interface{}
	_ = json.Unmarshal(dataBytes, &got)

	// Use SanitizeInput for expected values
	assert.Equal(t, SanitizeInput(orig["content"].(string)), got["content"])
	assert.Equal(t, SanitizeInput(orig["path"].(string)), got["path"])
	assert.Equal(t, SanitizeInput(orig["old_content"].(string)), got["old_content"])
	assert.Equal(t, SanitizeInput(orig["new_content"].(string)), got["new_content"])

	// Check ContentLength matches
	assert.Equal(t, int64(len(dataBytes)), r.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_NoChange(t *testing.T) {
	r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader("not-json"))
	SanitizeRequestBody(r)
	got, _ := io.ReadAll(r.Body)
	assert.Equal(t, "not-json", string(got))
}

func TestValidationMiddleware_POST_SanitizesAndForwards(t *testing.T) {
	orig := map[string]interface{}{
		"content": "a\x00b" + string(rune(11)) + "c\n",
	}
	body, _ := json.Marshal(orig)

	var captured map[string]interface{}

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(data, &captured)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(data)
	})

	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(body))
	rr := httptest.NewRecorder()
	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)

	// Ensure content sanitized in forwarded request
	expectedContent := SanitizeInput(orig["content"].(string))
	assert.Equal(t, expectedContent, captured["content"])

	// Response is the sanitized JSON as well
	var resp map[string]interface{}
	_ = json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.Equal(t, expectedContent, resp["content"])
}

func TestValidationMiddleware_GET_Passthrough(t *testing.T) {
	var called bool
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusTeapot)
	})
	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()
	mw.ServeHTTP(rr, req)

	assert.True(t, called)
	assert.Equal(t, http.StatusTeapot, rr.Code)
}

type errReadCloser struct{}

func (e *errReadCloser) Read(p []byte) (int, error) { return 0, io.ErrUnexpectedEOF }
func (e *errReadCloser) Close() error               { return nil }

func TestValidationMiddleware_ReadErrorReturnsBadRequest(t *testing.T) {
	nextCalled := false
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nextCalled = true
	})
	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/", nil)
	req.Body = &errReadCloser{}
	rr := httptest.NewRecorder()
	mw.ServeHTTP(rr, req)

	assert.False(t, nextCalled)
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Body.String(), "Failed to read request body")
}

func TestGetAndClearValidationErrors_CopyAndClear(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	errs := []ValidationError{
		{Field: "a", Reason: "A", Time: time.Now()},
	}
	logValidationErrors(errs)

	got1 := GetValidationErrors()
	assert.Len(t, got1, 1)

	// Modify returned slice; underlying store should not change
	got1[0].Field = "modified"
	got2 := GetValidationErrors()
	assert.Equal(t, "a", got2[0].Field)

	// Clear and ensure empty
	ClearValidationErrors()
	got3 := GetValidationErrors()
	assert.Empty(t, got3)
}

func TestLogValidationErrors_CappedAt100(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	var batch []ValidationError
	for i := 0; i < 120; i++ {
		batch = append(batch, ValidationError{
			Field:  "f-" + strconvI(i),
			Reason: "err-" + strconvI(i),
			Time:   time.Now(),
		})
	}
	logValidationErrors(batch)

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	// should contain last 100 entries: indices 20..119
	assert.Equal(t, "f-20", got[0].Field)
	assert.Equal(t, "err-20", got[0].Reason)
	assert.Equal(t, "f-119", got[99].Field)
	assert.Equal(t, "err-119", got[99].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("ab\x00cd"))
	assert.False(t, containsNullBytes("abcd"))
}

// helper without importing strconv to keep dependencies minimal
func strconvI(i int) string {
	const digits = "0123456789"
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
