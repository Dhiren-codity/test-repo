package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
	"unicode"
)

const (
	MaxContentSize = 1000000
	MaxPathLength  = 500
)

type ValidationError struct {
	Field  string    `json:"field"`
	Reason string    `json:"reason"`
	Time   time.Time `json:"timestamp"`
}

var (
	validationErrors []ValidationError
	validationMutex  sync.RWMutex
)

func ValidateParseRequest(content, path string) []ValidationError {
	var errors []ValidationError

	if content == "" {
		errors = append(errors, ValidationError{
			Field:  "content",
			Reason: "Content is required and cannot be empty",
			Time:   time.Now(),
		})
	} else if len(content) > MaxContentSize {
		errors = append(errors, ValidationError{
			Field:  "content",
			Reason: "Content exceeds maximum size of 1MB",
			Time:   time.Now(),
		})
	} else if containsNullBytes(content) {
		errors = append(errors, ValidationError{
			Field:  "content",
			Reason: "Content contains invalid null bytes",
			Time:   time.Now(),
		})
	}

	if len(path) > MaxPathLength {
		errors = append(errors, ValidationError{
			Field:  "path",
			Reason: "Path exceeds maximum length",
			Time:   time.Now(),
		})
	}

	if strings.Contains(path, "..") || strings.Contains(path, "~/") {
		errors = append(errors, ValidationError{
			Field:  "path",
			Reason: "Path contains potential directory traversal",
			Time:   time.Now(),
		})
	}

	logValidationErrors(errors)
	return errors
}

func ValidateDiffRequest(oldContent, newContent string) []ValidationError {
	var errors []ValidationError

	if oldContent == "" {
		errors = append(errors, ValidationError{
			Field:  "old_content",
			Reason: "Old content is required",
			Time:   time.Now(),
		})
	} else if len(oldContent) > MaxContentSize {
		errors = append(errors, ValidationError{
			Field:  "old_content",
			Reason: "Old content exceeds maximum size",
			Time:   time.Now(),
		})
	}

	if newContent == "" {
		errors = append(errors, ValidationError{
			Field:  "new_content",
			Reason: "New content is required",
			Time:   time.Now(),
		})
	} else if len(newContent) > MaxContentSize {
		errors = append(errors, ValidationError{
			Field:  "new_content",
			Reason: "New content exceeds maximum size",
			Time:   time.Now(),
		})
	}

	logValidationErrors(errors)
	return errors
}

func SanitizeInput(input string) string {
	var result strings.Builder
	for _, r := range input {
		if r == 0 || (r >= 1 && r <= 8) || r == 11 || r == 12 || (r >= 14 && r <= 31) || r == 127 {
			continue
		}
		if unicode.IsControl(r) && r != '\n' && r != '\r' && r != '\t' {
			continue
		}
		result.WriteRune(r)
	}
	return result.String()
}

func SanitizeRequestBody(r *http.Request) {
	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		return
	}
	r.Body.Close()

	var data map[string]interface{}
	if err := json.Unmarshal(bodyBytes, &data); err == nil {
		if content, ok := data["content"].(string); ok {
			data["content"] = SanitizeInput(content)
		}
		if path, ok := data["path"].(string); ok {
			data["path"] = SanitizeInput(path)
		}
		if oldContent, ok := data["old_content"].(string); ok {
			data["old_content"] = SanitizeInput(oldContent)
		}
		if newContent, ok := data["new_content"].(string); ok {
			data["new_content"] = SanitizeInput(newContent)
		}

		sanitizedBody, _ := json.Marshal(data)
		r.Body = io.NopCloser(bytes.NewBuffer(sanitizedBody))
		r.ContentLength = int64(len(sanitizedBody))
	} else {
		r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
	}
}

func ValidationMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			next.ServeHTTP(w, r)
			return
		}

		bodyBytes, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Failed to read request body", http.StatusBadRequest)
			return
		}
		r.Body.Close()
		r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))

		var data map[string]interface{}
		if err := json.Unmarshal(bodyBytes, &data); err == nil {
			if content, ok := data["content"].(string); ok {
				data["content"] = SanitizeInput(content)
			}
			if path, ok := data["path"].(string); ok {
				data["path"] = SanitizeInput(path)
			}
			if oldContent, ok := data["old_content"].(string); ok {
				data["old_content"] = SanitizeInput(oldContent)
			}
			if newContent, ok := data["new_content"].(string); ok {
				data["new_content"] = SanitizeInput(newContent)
			}

			sanitizedBody, _ := json.Marshal(data)
			r.Body = io.NopCloser(bytes.NewBuffer(sanitizedBody))
			r.ContentLength = int64(len(sanitizedBody))
		}

		next.ServeHTTP(w, r)
	})
}

func GetValidationErrors() []ValidationError {
	validationMutex.RLock()
	defer validationMutex.RUnlock()

	result := make([]ValidationError, len(validationErrors))
	copy(result, validationErrors)
	return result
}

func ClearValidationErrors() {
	validationMutex.Lock()
	defer validationMutex.Unlock()
	validationErrors = []ValidationError{}
}

func containsNullBytes(s string) bool {
	return strings.Contains(s, "\x00")
}

func logValidationErrors(errors []ValidationError) {
	if len(errors) == 0 {
		return
	}

	validationMutex.Lock()
	defer validationMutex.Unlock()

	validationErrors = append(validationErrors, errors...)

	if len(validationErrors) > 100 {
		validationErrors = validationErrors[len(validationErrors)-100:]
	}
}
