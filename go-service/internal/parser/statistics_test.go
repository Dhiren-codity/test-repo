package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()
	stats := sc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, len(stats.Languages))
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     10,
			Language: "Go",
			Lines:    []string{"l1", "l2", "l3"},
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 10, stats.TotalSize)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 10.0, stats.AverageSize, 1e-9)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFilesAggregations(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Language: "Go",
			Lines:    []string{"x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10"},
		},
		{
			Path:     "b.py",
			Size:     200,
			Language: "Python",
			Lines:    []string{"y1", "y2", "y3", "y4", "y5"},
		},
		{
			Path:     "c.go",
			Size:     50,
			Language: "Go",
			Lines:    []string{"z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "z9", "z10", "z11", "z12", "z13", "z14", "z15", "z16", "z17", "z18", "z19", "z20"},
		},
	}

	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 35, stats.TotalLines)
	assert.Equal(t, 350, stats.TotalSize)
	assert.Equal(t, "b.py", stats.LargestFile)
	assert.Equal(t, "c.go", stats.SmallestFile)

	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])

	assert.InDelta(t, 35.0/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 350.0/3.0, stats.AverageSize, 1e-9)
}

func TestStatisticsCalculator_CalculateFileStats_TiedSizesPreferFirst(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "first.txt",
			Size:     100,
			Language: "Text",
			Lines:    []string{"a"},
		},
		{
			Path:     "second.txt",
			Size:     100,
			Language: "Text",
			Lines:    []string{"b", "c"},
		},
	}

	stats := sc.CalculateFileStats(files)

	// When sizes are tied, LargestFile and SmallestFile should remain the first encountered.
	assert.Equal(t, "first.txt", stats.LargestFile)
	assert.Equal(t, "first.txt", stats.SmallestFile)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyLanguageKey(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "nolanguage.bin",
			Size:     1,
			Language: "",
			Lines:    []string{"line"},
		},
		{
			Path:     "langA.bin",
			Size:     2,
			Language: "A",
			Lines:    []string{"l1", "l2"},
		},
	}

	stats := sc.CalculateFileStats(files)

	// Expect count under empty-string key and proper count for "A".
	assert.Equal(t, 1, stats.Languages[""])
	assert.Equal(t, 1, stats.Languages["A"])
}

func TestStatisticsCalculator_CalculateFileStats_NilReceiver(t *testing.T) {
	var sc *StatisticsCalculator // nil receiver
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     10,
			Language: "Go",
			Lines:    []string{"1", "2"},
		},
	}
	// Method should not panic even with nil receiver because it doesn't dereference sc.
	stats := sc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 2, stats.TotalLines)
	assert.Equal(t, 10, stats.TotalSize)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}
