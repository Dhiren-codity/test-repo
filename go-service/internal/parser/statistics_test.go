package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func cf(path string, lines int, size int, lang string) *CodeFile {
	l := make([]string, lines)
	for i := range l {
		l[i] = "line"
	}
	return &CodeFile{
		Path:     path,
		Lines:    l,
		Size:     size,
		Language: lang,
	}
}

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)
}

func TestCalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.NotNil(t, stats.Languages)
	assert.Empty(t, stats.Languages)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestCalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		cf("a.go", 3, 100, "Go"),
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.Equal(t, map[string]int{"Go": 1}, stats.Languages)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}

func TestCalculateFileStats_MultipleFilesVariousSizes(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		cf("a.go", 3, 100, "Go"),
		cf("b.py", 0, 50, "Python"),
		cf("c.go", 5, 200, "Go"),
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 8, stats.TotalLines)  // 3 + 0 + 5
	assert.Equal(t, 350, stats.TotalSize) // 100 + 50 + 200
	assert.Equal(t, map[string]int{"Go": 2, "Python": 1}, stats.Languages)
	assert.InDelta(t, float64(8)/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, float64(350)/3.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "c.go", stats.LargestFile)
	assert.Equal(t, "b.py", stats.SmallestFile)
}

func TestCalculateFileStats_TiesForLargestAndSmallest_PicksFirstOccurrence(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		cf("a.go", 1, 100, "Go"), // initial min and max
		cf("b.go", 2, 200, "Go"), // becomes new max
		cf("c.go", 3, 200, "Go"), // ties max, should not replace b.go
		cf("d.go", 4, 100, "Go"), // ties min, should not replace a.go
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, "b.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}
