package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func mkLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "line"
	}
	return lines
}

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats([]*CodeFile{})
	assert.NotNil(t, stats)

	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)

	// averages and file names should be zero-values
	assert.InDelta(t, 0.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 0.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)

	// languages map should be initialized and empty
	if assert.NotNil(t, stats.Languages) {
		assert.Len(t, stats.Languages, 0)
	}
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "main.go",
			Size:     100,
			Lines:    mkLines(3),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	assert.Equal(t, "main.go", stats.LargestFile)
	assert.Equal(t, "main.go", stats.SmallestFile)

	if assert.NotNil(t, stats.Languages) {
		assert.Equal(t, 1, stats.Languages["Go"])
		assert.Len(t, stats.Languages, 1)
	}
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles_TotalsAndExtremesAndLanguages(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{Path: "a.go", Size: 10, Lines: mkLines(3), Language: "Go"},
		{Path: "b.py", Size: 200, Lines: mkLines(5), Language: "Python"},
		{Path: "c.js", Size: 200, Lines: mkLines(7), Language: "JavaScript"},
		{Path: "d.go", Size: 5, Lines: mkLines(0), Language: "Go"},
		{Path: "e.go", Size: 5, Lines: mkLines(1), Language: "Go"},
		{Path: "f.txt", Size: 0, Lines: mkLines(2), Language: ""},
	}

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 6, stats.TotalFiles)
	assert.Equal(t, 18, stats.TotalLines)            // 3+5+7+0+1+2
	assert.Equal(t, 420, stats.TotalSize)            // 10+200+200+5+5+0
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9) // 18/6
	assert.InDelta(t, 70.0, stats.AverageSize, 1e-9) // 420/6

	// Largest should be first 200-sized file "b.py" (tie should not override)
	assert.Equal(t, "b.py", stats.LargestFile)
	// Smallest should be first 5-sized file "d.go" (tie should not override)
	assert.Equal(t, "d.go", stats.SmallestFile)

	if assert.NotNil(t, stats.Languages) {
		assert.Equal(t, 3, stats.Languages["Go"])
		assert.Equal(t, 1, stats.Languages["Python"])
		assert.Equal(t, 1, stats.Languages["JavaScript"])
		assert.Equal(t, 1, stats.Languages[""])
		assert.Len(t, stats.Languages, 4)
	}
}

func TestStatisticsCalculator_CalculateFileStats_NilReceiver(t *testing.T) {
	// Method does not dereference receiver; calling on nil should work.
	var sc *StatisticsCalculator

	files := []*CodeFile{
		{Path: "x.go", Size: 10, Lines: mkLines(2), Language: "Go"},
		{Path: "y.go", Size: 20, Lines: mkLines(4), Language: "Go"},
	}

	stats := sc.CalculateFileStats(files)
	assert.NotNil(t, stats)

	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 6, stats.TotalLines) // 2+4
	assert.Equal(t, 30, stats.TotalSize) // 10+20
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 15.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "y.go", stats.LargestFile)
	assert.Equal(t, "x.go", stats.SmallestFile)
	if assert.NotNil(t, stats.Languages) {
		assert.Equal(t, 2, stats.Languages["Go"])
	}
}
