package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func mkLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = ""
	}
	return lines
}

func mkFile(path string, size int, language string, numLines int) *CodeFile {
	return &CodeFile{
		Path:     path,
		Size:     size,
		Language: language,
		Lines:    mkLines(numLines),
	}
}

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyOrNil(t *testing.T) {
	sc := NewStatisticsCalculator()

	t.Run("nil slice", func(t *testing.T) {
		stats := sc.CalculateFileStats(nil)
		assert.NotNil(t, stats)
		assert.Equal(t, 0, stats.TotalFiles)
		assert.Equal(t, 0, stats.TotalLines)
		assert.Equal(t, 0, stats.TotalSize)
		assert.InDelta(t, 0.0, stats.AverageLines, 1e-9)
		assert.InDelta(t, 0.0, stats.AverageSize, 1e-9)
		assert.Equal(t, "", stats.LargestFile)
		assert.Equal(t, "", stats.SmallestFile)
		assert.NotNil(t, stats.Languages)
		assert.Len(t, stats.Languages, 0)
	})

	t.Run("empty slice", func(t *testing.T) {
		stats := sc.CalculateFileStats([]*CodeFile{})
		assert.NotNil(t, stats)
		assert.Equal(t, 0, stats.TotalFiles)
		assert.Equal(t, 0, stats.TotalLines)
		assert.Equal(t, 0, stats.TotalSize)
		assert.InDelta(t, 0.0, stats.AverageLines, 1e-9)
		assert.InDelta(t, 0.0, stats.AverageSize, 1e-9)
		assert.Equal(t, "", stats.LargestFile)
		assert.Equal(t, "", stats.SmallestFile)
		assert.NotNil(t, stats.Languages)
		assert.Len(t, stats.Languages, 0)
	})
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		mkFile("a.go", 100, "Go", 3),
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Len(t, stats.Languages, 1)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		mkFile("a.go", 120, "Go", 10),
		mkFile("b.py", 80, "Python", 20),
		mkFile("c.go", 200, "Go", 5),
		mkFile("e.txt", 50, "Text", 0),
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 4, stats.TotalFiles)
	assert.Equal(t, 35, stats.TotalLines)
	assert.Equal(t, 450, stats.TotalSize)
	assert.InDelta(t, 8.75, stats.AverageLines, 1e-9)
	assert.InDelta(t, 112.5, stats.AverageSize, 1e-9)
	assert.Equal(t, "c.go", stats.LargestFile)
	assert.Equal(t, "e.txt", stats.SmallestFile)

	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
	assert.Equal(t, 1, stats.Languages["Text"])
	assert.Len(t, stats.Languages, 3)
}

func TestStatisticsCalculator_CalculateFileStats_TiesForSize(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		mkFile("a.go", 100, "Go", 1),
		mkFile("b.py", 100, "Python", 2),
		mkFile("c.rs", 100, "Rust", 3),
	}

	stats := sc.CalculateFileStats(files)

	// When sizes are equal, first file should remain both largest and smallest due to strict >/< checks
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 6, stats.TotalLines)
	assert.Equal(t, 300, stats.TotalSize)
	assert.InDelta(t, 2.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
	assert.Equal(t, 1, stats.Languages["Rust"])
	assert.Len(t, stats.Languages, 3)
}
