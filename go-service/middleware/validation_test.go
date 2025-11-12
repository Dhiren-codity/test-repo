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
	"github.com/stretchr/testify/require"
)

func TestValidateParseRequest_ContentValidation(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name       string
		content    string
		path       string
		wantErrors []ValidationError
	}{
		{
			name:    "empty content",
			content: "",
			wantErrors: []ValidationError{
				{Field: "content", Reason: "Content is required and cannot be empty"},
			},
		},
		{
			name:    "oversize content",
			content: strings.Repeat("a", MaxContentSize+1),
			wantErrors: []ValidationError{
				{Field: "content", Reason: "Content exceeds maximum size of 1MB"},
			},
		},
		{
			name:    "content contains null byte",
			content: "foo\x00bar",
			wantErrors: []ValidationError{
				{Field: "content", Reason: "Content contains invalid null bytes"},
			},
		},
		{
			name:    "valid content and path",
			content: "hello world",
			path:    "some/valid/path",
			// no errors
		},
		{
			name:    "path too long",
			content: "ok",
			path:    strings.Repeat("a", MaxPathLength+1),
			wantErrors: []ValidationError{
				{Field: "path", Reason: "Path exceeds maximum length"},
			},
		},
		{
			name:    "path contains traversal ..",
			content: "ok",
			path:    "../etc/passwd",
			wantErrors: []ValidationError{
				{Field: "path", Reason: "Path contains potential directory traversal"},
			},
		},
		{
			name:    "path contains traversal ~/",
			content: "ok",
			path:    "~/secrets",
			wantErrors: []ValidationError{
				{Field: "path", Reason: "Path contains potential directory traversal"},
			},
		},
	}

	for _, tt := range tests {
		errs := ValidateParseRequest(tt.content, tt.path)

		if len(tt.wantErrors) == 0 {
			assert.Empty(t, errs, tt.name)
		} else {
			require.NotEmpty(t, errs, tt.name)
			// Compare only Field and Reason
			got := make([]struct {
				Field  string
				Reason string
			}, len(errs))
			for i, e := range errs {
				got[i] = struct {
					Field  string
					Reason string
				}{Field: e.Field, Reason: e.Reason}
			}
			want := make([]struct {
				Field  string
				Reason string
			}, len(tt.wantErrors))
			for i, e := range tt.wantErrors {
				want[i] = struct {
					Field  string
					Reason string
				}{Field: e.Field, Reason: e.Reason}
			}
			assert.Equal(t, want, got, tt.name)
		}
	}

	// Validate logging side effect by comparing counts
	ClearValidationErrors()
	_ = ValidateParseRequest("", "")
	logged := GetValidationErrors()
	require.NotEmpty(t, logged)
	assert.Equal(t, "content", logged[0].Field)
	assert.Equal(t, "Content is required and cannot be empty", logged[0].Reason)

	// Ensure ClearValidationErrors empties the store
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestValidateDiffRequest(t *testing.T) {
	ClearValidationErrors()

	t.Run("both empty", func(t *testing.T) {
		errs := ValidateDiffRequest("", "")
		require.Len(t, errs, 2)
		fields := []string{errs[0].Field, errs[1].Field}
		assert.ElementsMatch(t, []string{"old_content", "new_content"}, fields)
	})

	t.Run("old content oversize", func(t *testing.T) {
		errs := ValidateDiffRequest(strings.Repeat("x", MaxContentSize+1), "ok")
		require.Len(t, errs, 1)
		assert.Equal(t, "old_content", errs[0].Field)
		assert.Equal(t, "Old content exceeds maximum size", errs[0].Reason)
	})

	t.Run("new content oversize", func(t *testing.T) {
		errs := ValidateDiffRequest("ok", strings.Repeat("x", MaxContentSize+1))
		require.Len(t, errs, 1)
		assert.Equal(t, "new_content", errs[0].Field)
		assert.Equal(t, "New content exceeds maximum size", errs[0].Reason)
	})

	t.Run("valid contents", func(t *testing.T) {
		errs := ValidateDiffRequest("old", "new")
		assert.Empty(t, errs)
	})

	// Validate errors logged
	ClearValidationErrors()
	_ = ValidateDiffRequest("", "")
	logged := GetValidationErrors()
	require.Len(t, logged, 2)
	assert.ElementsMatch(t, []string{"old_content", "new_content"}, []string{logged[0].Field, logged[1].Field})
	ClearValidationErrors()
}

func TestSanitizeInput(t *testing.T) {
	// include various control characters to be removed and some to be preserved
	in := "A\x00B" + "C\x07D" + "E\x0BF" + "G\x0CH" + "I\x0EJ" + "K\x7FL" + "M\nN" + "O\rP" + "Q\tR"
	out := SanitizeInput(in)
	// expected: all controls removed except \n, \r, \t
	assert.Equal(t, "ABCD"[:2]+"CD"+"EF"[:1]+"F"+"GH"[:1]+"H"+"IJ"[:1]+"J"+"KL"[:1]+"L"+"M\nN"+"O\rP"+"Q\tR", out)
	// A clearer explicit expected string:
	assert.Equal(t, "AB"+"CD"+"EF"+"GH"+"IJ"+"KL"+"M\nN"+"O\rP"+"Q\tR", out)
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	body := map[string]string{
		"content":     "a\x00b",
		"path":        "p\x0Bq",
		"old_content": "o\x7Fr",
		"new_content": "n\x01m",
	}
	raw, _ := json.Marshal(body)

	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))
	err := func() error {
		SanitizeRequestBody(r)
		return nil
	}()
	require.NoError(t, err)

	// Read back body and verify sanitized
	data, err := io.ReadAll(r.Body)
	require.NoError(t, err)
	var got map[string]string
	require.NoError(t, json.Unmarshal(data, &got))

	assert.Equal(t, "ab", got["content"])
	assert.Equal(t, "pq", got["path"])
	assert.Equal(t, "or", got["old_content"])
	assert.Equal(t, "nm", got["new_content"])
	assert.Equal(t, int64(len(data)), r.ContentLength)
}

func TestSanitizeRequestBody_NonJSON(t *testing.T) {
	orig := []byte("not json")
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(orig))
	SanitizeRequestBody(r)
	data, err := io.ReadAll(r.Body)
	require.NoError(t, err)
	assert.Equal(t, orig, data)
}

func TestValidationMiddleware_POST_Sanitizes(t *testing.T) {
	body := map[string]string{
		"content":     "x\x00y",
		"path":        "a\x0Bb",
		"old_content": "c\x7Fd",
		"new_content": "e\x01f",
	}
	raw, _ := json.Marshal(body)

	var received []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		received = b
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)
	require.Equal(t, http.StatusOK, rr.Code)

	var got map[string]string
	require.NoError(t, json.Unmarshal(received, &got))
	assert.Equal(t, "xy", got["content"])
	assert.Equal(t, "ab", got["path"])
	assert.Equal(t, "cd", got["old_content"])
	assert.Equal(t, "ef", got["new_content"])
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	// Middleware should not modify non-POST requests
	body := map[string]string{"content": "x\x00y"}
	raw, _ := json.Marshal(body)

	var received []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		received = b
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewReader(raw))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)
	require.Equal(t, http.StatusOK, rr.Code)

	// Should be unchanged (no sanitization on GET)
	assert.Equal(t, raw, received)
}

func TestGetAndClearValidationErrorsIsolation(t *testing.T) {
	ClearValidationErrors()
	errs := []ValidationError{
		{Field: "a", Reason: "ra", Time: time.Now()},
		{Field: "b", Reason: "rb", Time: time.Now()},
	}
	logValidationErrors(errs)

	// Get a copy and mutate local slice; internal store should be unaffected
	copy1 := GetValidationErrors()
	require.Len(t, copy1, 2)
	copy1[0].Field = "mutated"
	copy2 := GetValidationErrors()
	assert.Equal(t, "a", copy2[0].Field)

	// Clearing should empty the store
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_Cap100(t *testing.T) {
	ClearValidationErrors()

	// Log 110 individual errors
	for i := 0; i < 110; i++ {
		logValidationErrors([]ValidationError{
			{Field: "err" + strconvI(i), Reason: "r" + strconvI(i), Time: time.Now()},
		})
	}

	all := GetValidationErrors()
	require.Len(t, all, 100)
	// Should keep the last 100 (i.e., 10..109)
	assert.Equal(t, "err10", all[0].Field)
	assert.Equal(t, "r10", all[0].Reason)
	assert.Equal(t, "err109", all[99].Field)
	assert.Equal(t, "r109", all[99].Reason)

	// Logging empty slice should not change
	prev := GetValidationErrors()
	logValidationErrors(nil)
	now := GetValidationErrors()
	assert.Equal(t, prev, now)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

// helper: strconv.Itoa without importing strconv for minimal deps
func strconvI(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	neg := false
	if i < 0 {
		neg = true
		i = -i
	}
	var buf [20]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = digits[i%10]
		i /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
