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

func TestValidateParseRequest_ContentAndPathValidations(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		path        string
		wantFields  []string
		wantReasons []string
	}{
		{
			name:        "empty content",
			content:     "",
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content is required and cannot be empty"},
		},
		{
			name:        "oversize content",
			content:     strings.Repeat("a", MaxContentSize+1),
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content exceeds maximum size of 1MB"},
		},
		{
			name:        "null bytes in content",
			content:     "hello\x00world",
			path:        "",
			wantFields:  []string{"content"},
			wantReasons: []string{"Content contains invalid null bytes"},
		},
		{
			name:        "path too long",
			content:     "ok",
			path:        strings.Repeat("a", MaxPathLength+1),
			wantFields:  []string{"path"},
			wantReasons: []string{"Path exceeds maximum length"},
		},
		{
			name:        "path traversal dotdot",
			content:     "ok",
			path:        "a/../../b",
			wantFields:  []string{"path"},
			wantReasons: []string{"Path contains potential directory traversal"},
		},
		{
			name:        "path traversal tilde",
			content:     "ok",
			path:        "~/foo/bar",
			wantFields:  []string{"path"},
			wantReasons: []string{"Path contains potential directory traversal"},
		},
		{
			name:        "multiple errors",
			content:     "",
			path:        "../etc/passwd",
			wantFields:  []string{"content", "path"},
			wantReasons: []string{"Content is required and cannot be empty", "Path contains potential directory traversal"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Equal(t, len(tt.wantFields), len(errs))
			for i, field := range tt.wantFields {
				assert.Equal(t, field, errs[i].Field)
				assert.Equal(t, tt.wantReasons[i], errs[i].Reason)
				assert.False(t, errs[i].Time.IsZero())
			}
			// Logged
			logged := GetValidationErrors()
			assert.Equal(t, len(tt.wantFields), len(logged))
		})
	}
}

func TestValidateParseRequest_NoErrors_NoLog(t *testing.T) {
	ClearValidationErrors()
	errs := ValidateParseRequest("valid content", "valid/path.txt")
	assert.Len(t, errs, 0)
	assert.Len(t, GetValidationErrors(), 0)
}

func TestValidateDiffRequest_Cases(t *testing.T) {
	t.Run("both empty", func(t *testing.T) {
		ClearValidationErrors()
		errs := ValidateDiffRequest("", "")
		assert.Len(t, errs, 2)
		fields := []string{errs[0].Field, errs[1].Field}
		assert.Contains(t, fields, "old_content")
		assert.Contains(t, fields, "new_content")

		logged := GetValidationErrors()
		assert.Len(t, logged, 2)
	})

	t.Run("oversize old content", func(t *testing.T) {
		ClearValidationErrors()
		oversize := strings.Repeat("x", MaxContentSize+1)
		errs := ValidateDiffRequest(oversize, "new")
		assert.Len(t, errs, 1)
		assert.Equal(t, "old_content", errs[0].Field)
		assert.Contains(t, errs[0].Reason, "exceeds maximum size")

		logged := GetValidationErrors()
		assert.Len(t, logged, 1)
	})

	t.Run("valid both", func(t *testing.T) {
		ClearValidationErrors()
		errs := ValidateDiffRequest("old", "new")
		assert.Len(t, errs, 0)
		assert.Len(t, GetValidationErrors(), 0)
	})
}

func TestSanitizeInput_RemovesControlChars(t *testing.T) {
	in := "A\x00B\x07C\nD\tE\rF\x1FG"
	out := SanitizeInput(in)
	assert.Equal(t, "ABC\nD\tE\rFG", out)

	// Ensure no ASCII control code remains except allowed \n \r \t
	for _, r := range out {
		if r < 32 || r == 127 {
			assert.Contains(t, "\n\r\t", string(r))
		}
	}
}

func TestSanitizeRequestBody_SanitizesJSONFields(t *testing.T) {
	body := `{"content":"Hi\u0000there","path":"abc\u0007def","old_content":"ok","new_content":"fine"}`
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBufferString(body))
	r.Header.Set("Content-Type", "application/json")

	SanitizeRequestBody(r)
	b, err := io.ReadAll(r.Body)
	assert.NoError(t, err)

	var got map[string]string
	err = json.Unmarshal(b, &got)
	assert.NoError(t, err)

	assert.Equal(t, "Hithere", got["content"])
	assert.Equal(t, "abcdef", got["path"])
	assert.Equal(t, "ok", got["old_content"])
	assert.Equal(t, "fine", got["new_content"])

	assert.Equal(t, int64(len(b)), r.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_PreservesBody(t *testing.T) {
	orig := `{"content":"ok","path":"abc"} trailing`
	r := httptest.NewRequest(http.MethodPost, "/x", bytes.NewBufferString(orig))
	SanitizeRequestBody(r)

	b, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(b))
}

func TestValidationMiddleware_POST_SanitizesBody(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		w.Write(b)
	})
	mw := ValidationMiddleware(next)

	body := `{"content":"A\u0000B","path":"C\u0007D","old_content":"X","new_content":"Y"}`
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)
	resBody := rr.Body.Bytes()

	var got map[string]string
	err := json.Unmarshal(resBody, &got)
	assert.NoError(t, err)
	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "CD", got["path"])
	assert.Equal(t, "X", got["old_content"])
	assert.Equal(t, "Y", got["new_content"])
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		w.Write(b)
	})
	mw := ValidationMiddleware(next)

	orig := `{"content":"A\u0000B"}`
	req := httptest.NewRequest(http.MethodGet, "/parse", bytes.NewBufferString(orig))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)
	assert.Equal(t, orig, rr.Body.String())
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "a", Reason: "ra", Time: now},
		{Field: "b", Reason: "rb", Time: now},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 2)

	ClearValidationErrors()
	errs2 := GetValidationErrors()
	assert.Len(t, errs2, 0)
}

func TestGetValidationErrors_ReturnsCopy(t *testing.T) {
	ClearValidationErrors()
	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "x", Reason: "rx", Time: now},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 1)
	errs[0].Field = "mutated"

	errs2 := GetValidationErrors()
	assert.Equal(t, "x", errs2[0].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func TestLogValidationErrors_Limit100(t *testing.T) {
	ClearValidationErrors()
	var batch []ValidationError
	for i := 0; i < 150; i++ {
		batch = append(batch, ValidationError{
			Field:  "f" + strconvI(i),
			Reason: "r",
			Time:   time.Now(),
		})
	}
	logValidationErrors(batch)

	errs := GetValidationErrors()
	assert.Len(t, errs, 100)
	assert.Equal(t, "f50", errs[0].Field)
	assert.Equal(t, "f149", errs[len(errs)-1].Field)
}

// Helper strconv for integer to string without importing strconv to keep imports concise
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
