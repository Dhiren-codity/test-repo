package api

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"polyglot-codebase/go-service/internal/parser"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

type CacheEntry struct {
	Data      interface{}
	ExpiresAt time.Time
}

type Handler struct {
	parser *parser.Parser
	cache  map[string]CacheEntry
	mu     sync.RWMutex
}

func NewHandler() *Handler {
	return &Handler{
		parser: parser.NewParser(),
		cache:  make(map[string]CacheEntry),
	}
}

type ParseRequest struct {
	Content string `json:"content" binding:"required"`
	Path    string `json:"path" binding:"required"`
}

type DiffRequest struct {
	OldContent string `json:"old_content" binding:"required"`
	NewContent string `json:"new_content" binding:"required"`
}

type MetricsRequest struct {
	Content string `json:"content" binding:"required"`
}

func (h *Handler) ParseFile(c *gin.Context) {
	var req ParseRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	cacheKey := h.generateCacheKey("parse", req.Content+req.Path)

	if cached, found := h.getFromCache(cacheKey); found {
		c.Header("X-Cache-Hit", "true")
		c.JSON(http.StatusOK, cached)
		return
	}

	file, err := h.parser.ParseFile(req.Content, req.Path)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	h.setCache(cacheKey, file, 5*time.Minute)
	c.Header("X-Cache-Hit", "false")
	c.JSON(http.StatusOK, file)
}

func (h *Handler) AnalyzeDiff(c *gin.Context) {
	var req DiffRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	diff, err := h.parser.AnalyzeDiff(req.OldContent, req.NewContent)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, diff)
}

func (h *Handler) CalculateMetrics(c *gin.Context) {
	var req MetricsRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	cacheKey := h.generateCacheKey("metrics", req.Content)

	if cached, found := h.getFromCache(cacheKey); found {
		c.Header("X-Cache-Hit", "true")
		c.JSON(http.StatusOK, cached)
		return
	}

	metrics := h.parser.CalculateMetrics(req.Content)
	h.setCache(cacheKey, metrics, 5*time.Minute)
	c.Header("X-Cache-Hit", "false")
	c.JSON(http.StatusOK, metrics)
}

func (h *Handler) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "healthy",
		"service": "go-parser",
	})
}

func (h *Handler) generateCacheKey(prefix, data string) string {
	hash := sha256.Sum256([]byte(data))
	return prefix + "_" + hex.EncodeToString(hash[:])
}

func (h *Handler) getFromCache(key string) (interface{}, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	entry, exists := h.cache[key]
	if !exists {
		return nil, false
	}

	if time.Now().After(entry.ExpiresAt) {
		return nil, false
	}

	return entry.Data, true
}

func (h *Handler) setCache(key string, data interface{}, ttl time.Duration) {
	h.mu.Lock()
	defer h.mu.Unlock()

	h.cache[key] = CacheEntry{
		Data:      data,
		ExpiresAt: time.Now().Add(ttl),
	}
}

func (h *Handler) ClearCache(c *gin.Context) {
	h.mu.Lock()
	defer h.mu.Unlock()

	h.cache = make(map[string]CacheEntry)

	c.JSON(http.StatusOK, gin.H{
		"message": "Cache cleared successfully",
	})
}
