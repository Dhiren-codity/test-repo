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
	t.Cleanup(ClearValidationErrors)

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
			path:       "file.txt",
			wantFields: []string{"content"},
			wantReason: []string{"Content is required and cannot be empty"},
		},
		{
			name:       "content exceeds max size",
			content:    strings.Repeat("a", MaxContentSize+1),
			path:       "file.txt",
			wantFields: []string{"content"},
			wantReason: []string{"Content exceeds maximum size of 1MB"},
		},
		{
			name:       "content contains null bytes",
			content:    "a\x00b",
			path:       "file.txt",
			wantFields: []string{"content"},
			wantReason: []string{"Content contains invalid null bytes"},
		},
		{
			name:       "valid content",
			content:    "hello world",
			path:       "file.txt",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		ClearValidationErrors()
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if tt.wantFields == nil {
				assert.Len(t, errs, 0)
				assert.Len(t, GetValidationErrors(), 0)
				return
			}
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				assert.Equal(t, tt.wantReason[i], e.Reason)
			}
			logged := GetValidationErrors()
			assert.Equal(t, len(tt.wantFields), len(logged))
		})
	}
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	tests := []struct {
		name       string
		content    string
		path       string
		wantFields []string
		wantReason []string
	}{
		{
			name:       "path exceeds maximum length",
			content:    "ok",
			path:       strings.Repeat("a", MaxPathLength+1),
			wantFields: []string{"path"},
			wantReason: []string{"Path exceeds maximum length"},
		},
		{
			name:       "path contains traversal ..",
			content:    "ok",
			path:       "../etc/passwd",
			wantFields: []string{"path"},
			wantReason: []string{"Path contains potential directory traversal"},
		},
		{
			name:       "path contains traversal tilde",
			content:    "ok",
			path:       "~/home/user",
			wantFields: []string{"path"},
			wantReason: []string{"Path contains potential directory traversal"},
		},
		{
			name:       "path with both long and traversal",
			content:    "ok",
			path:       strings.Repeat("a", MaxPathLength-2) + "../",
			wantFields: []string{"path", "path"},
			wantReason: []string{"Path exceeds maximum length", "Path contains potential directory traversal"},
		},
		{
			name:       "valid path and content",
			content:    "ok",
			path:       "some/valid/path.txt",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		ClearValidationErrors()
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if tt.wantFields == nil {
				assert.Len(t, errs, 0)
				assert.Len(t, GetValidationErrors(), 0)
				return
			}
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				assert.Equal(t, tt.wantReason[i], e.Reason)
			}
			logged := GetValidationErrors()
			assert.Equal(t, len(tt.wantFields), len(logged))
		})
	}
}

func TestValidateParseRequest_MultipleErrorsAccumulation(t *testing.T) {
	ClearValidationErrors()
	t.Cleanup(ClearValidationErrors)

	content := ""
	path := strings.Repeat("a", MaxPathLength-2) + "../"
	errs := ValidateParseRequest(content, path)
	// Should include one error for content and two for path
	assert.Equal(t, 3, len(errs))
	fields := []string{errs[0].Field, errs[1].Field, errs[2].Field}
	reasons := []string{errs[0].Reason, errs[1].Reason, errs[2].Reason}
	assert.Contains(t, fields, "content")
	assert.Contains(t, reasons, "Content is required and cannot be empty")
	// order of path errors relative to each other may be path length then traversal based on code
	assert.Contains(t, fields, "path")
	assert.Contains(t, reasons, "Path exceeds maximum length")
	assert.Contains(t, reasons, "Path contains potential directory traversal")

	logged := GetValidationErrors()
	assert.Equal(t, 3, len(logged))
}

func TestValidateDiffRequest_Errors(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	tests := []struct {
		name       string
		oldC       string
		newC       string
		wantFields []string
		wantReason []string
	}{
		{
			name:       "both empty",
			oldC:       "",
			newC:       "",
			wantFields: []string{"old_content", "new_content"},
			wantReason: []string{"Old content is required", "New content is required"},
		},
		{
			name:       "old empty",
			oldC:       "",
			newC:       "abc",
			wantFields: []string{"old_content"},
			wantReason: []string{"Old content is required"},
		},
		{
			name:       "new empty",
			oldC:       "abc",
			newC:       "",
			wantFields: []string{"new_content"},
			wantReason: []string{"New content is required"},
		},
		{
			name:       "both exceed",
			oldC:       strings.Repeat("x", MaxContentSize+1),
			newC:       strings.Repeat("y", MaxContentSize+1),
			wantFields: []string{"old_content", "new_content"},
			wantReason: []string{"Old content exceeds maximum size", "New content exceeds maximum size"},
		},
		{
			name:       "valid both",
			oldC:       "old",
			newC:       "new",
			wantFields: nil,
			wantReason: nil,
		},
	}

	for _, tt := range tests {
		ClearValidationErrors()
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateDiffRequest(tt.oldC, tt.newC)
			if tt.wantFields == nil {
				assert.Len(t, errs, 0)
				assert.Len(t, GetValidationErrors(), 0)
				return
			}
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i := range errs {
				assert.Equal(t, tt.wantFields[i], errs[i].Field)
				assert.Equal(t, tt.wantReason[i], errs[i].Reason)
			}
			logged := GetValidationErrors()
			assert.Equal(t, len(tt.wantFields), len(logged))
		})
	}
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	input := "Hi\x00A\x01B\nC\tD\rE\x0BF\x7F\x14G"
	got := SanitizeInput(input)
	// Expect to remove: \x00, \x01, \x0B, \x7F, \x14; keep \n, \t, \r
	want := "HiAB\nC\tD\rEG"
	assert.Equal(t, want, got)
}

func TestSanitizeRequestBody_ValidJSON_SanitizedFields(t *testing.T) {
	body := `{
		"content":"Hello\u0000World",
		"path":"good/\u0001path",
		"old_content":"Old\u000BVal",
		"new_content":"New\u007FVal",
		"other":"untouched"
	}`
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))
	SanitizeRequestBody(r)

	// Read back sanitized body
	b, err := io.ReadAll(r.Body)
	assert.NoError(t, err)

	var data map[string]interface{}
	err = json.Unmarshal(b, &data)
	assert.NoError(t, err)

	assert.Equal(t, "HelloWorld", data["content"])
	assert.Equal(t, "good/path", data["path"])
	assert.Equal(t, "OldVal", data["old_content"])
	assert.Equal(t, "NewVal", data["new_content"])
	assert.Equal(t, "untouched", data["other"])
	// ContentLength should match length of sanitized JSON
	assert.Equal(t, int64(len(b)), r.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_Preserved(t *testing.T) {
	orig := "{invalid json"
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))
	SanitizeRequestBody(r)

	b, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(b))
}

func TestValidationMiddleware_SanitizesPOSTBody(t *testing.T) {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var m map[string]interface{}
		_ = json.Unmarshal(b, &m)
		content, _ := m["content"].(string)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(content))
	})

	srv := ValidationMiddleware(h)

	reqBody := `{"content":"Hi\u0000There"}`
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(reqBody))
	w := httptest.NewRecorder()

	srv.ServeHTTP(w, r)
	res := w.Result()
	defer res.Body.Close()

	assert.Equal(t, http.StatusOK, res.StatusCode)
	out, _ := io.ReadAll(res.Body)
	assert.Equal(t, "HiThere", string(out))
}

func TestValidationMiddleware_DoesNotSanitizeNonPOST(t *testing.T) {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var m map[string]interface{}
		_ = json.Unmarshal(b, &m)
		content, _ := m["content"].(string)
		_, _ = w.Write([]byte(content))
	})

	srv := ValidationMiddleware(h)

	reqBody := `{"content":"Hi\u0000There"}`
	r := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(reqBody))
	w := httptest.NewRecorder()

	srv.ServeHTTP(w, r)
	res := w.Result()
	defer res.Body.Close()

	out, _ := io.ReadAll(res.Body)
	assert.Equal(t, "Hi\x00There", string(out))
}

type errReadCloser struct{}

func (e errReadCloser) Read(p []byte) (int, error) { return 0, assert.AnError }
func (e errReadCloser) Close() error               { return nil }

func TestValidationMiddleware_ReadBodyError_Returns400(t *testing.T) {
	called := false
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
	})
	srv := ValidationMiddleware(h)

	r := httptest.NewRequest(http.MethodPost, "/", nil)
	r.Body = io.NopCloser(errReadCloser{})
	w := httptest.NewRecorder()

	srv.ServeHTTP(w, r)
	res := w.Result()
	defer res.Body.Close()

	assert.False(t, called)
	assert.Equal(t, http.StatusBadRequest, res.StatusCode)
	body, _ := io.ReadAll(res.Body)
	assert.Contains(t, string(body), "Failed to read request body")
}

func TestGetAndClearValidationErrors_CopyIsolation(t *testing.T) {
	ClearValidationErrors()
	t.Cleanup(ClearValidationErrors)

	// Log two errors
	errs := []ValidationError{
		{Field: "a", Reason: "ra", Time: time.Now()},
		{Field: "b", Reason: "rb", Time: time.Now()},
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Equal(t, 2, len(got))
	got[0].Field = "modified"

	// Ensure internal store not affected
	got2 := GetValidationErrors()
	assert.Equal(t, "a", got2[0].Field)

	// Clear works
	ClearValidationErrors()
	assert.Equal(t, 0, len(GetValidationErrors()))
}

func TestLogValidationErrors_CapacityLimit(t *testing.T) {
	ClearValidationErrors()
	t.Cleanup(ClearValidationErrors)

	var errs []ValidationError
	for i := 0; i < 105; i++ {
		errs = append(errs, ValidationError{
			Field:  "f" + strconvI(i),
			Reason: "r" + strconvI(i),
			Time:   time.Now(),
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Equal(t, 100, len(got))
	// Expect the first 5 were trimmed; first remaining is index 5
	assert.Equal(t, "f5", got[0].Field)
	assert.Equal(t, "r5", got[0].Reason)
	assert.Equal(t, "f104", got[99].Field)
	assert.Equal(t, "r104", got[99].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func strconvI(i int) string {
	return strconvIt(i)
}

// local integer to string without importing strconv directly in many places
func strconvIt(i int) string {
	var b [20]byte
	n := len(b)
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	for i > 0 {
		n--
		b[n] = byte('0' + i%10)
		i /= 10
	}
	if neg {
		n--
		b[n] = '-'
	}
	return string(b[n:])
}
