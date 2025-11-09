package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestStatisticsCalculator_CalculateFileStats(t *testing.T) {
	tests := []struct {
		name           string
		files          []*CodeFile
		wantTotalFiles int
		wantTotalLines int
		wantTotalSize  int
		wantAvgLines   float64
		wantAvgSize    float64
		wantLargest    string
		wantSmallest   string
		wantLangs      map[string]int
	}{
		{
			name:           "empty input",
			files:          nil,
			wantTotalFiles: 0,
			wantTotalLines: 0,
			wantTotalSize:  0,
			wantAvgLines:   0,
			wantAvgSize:    0,
			wantLargest:    "",
			wantSmallest:   "",
			wantLangs:      map[string]int{},
		},
		{
			name: "single file",
			files: []*CodeFile{
				{Path: "a.go", Lines: []string{"l1", "l2", "l3"}, Size: 120, Language: "Go"},
			},
			wantTotalFiles: 1,
			wantTotalLines: 3,
			wantTotalSize:  120,
			wantAvgLines:   3.0,
			wantAvgSize:    120.0,
			wantLargest:    "a.go",
			wantSmallest:   "a.go",
			wantLangs:      map[string]int{"Go": 1},
		},
		{
			name: "multiple files different sizes and languages",
			files: []*CodeFile{
				{Path: "a.go", Lines: []string{"1", "2", "3"}, Size: 120, Language: "Go"},
				{Path: "b.py", Lines: []string{"1", "2"}, Size: 50, Language: "Python"},
				{Path: "c.go", Lines: []string{"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}, Size: 200, Language: "Go"},
				{Path: "d.js", Lines: nil, Size: 0, Language: "JavaScript"},
			},
			wantTotalFiles: 4,
			wantTotalLines: 15,
			wantTotalSize:  370,
			wantAvgLines:   3.75,
			wantAvgSize:    92.5,
			wantLargest:    "c.go",
			wantSmallest:   "d.js",
			wantLangs:      map[string]int{"Go": 2, "Python": 1, "JavaScript": 1},
		},
		{
			name: "ties for largest and smallest choose first occurrence",
			files: []*CodeFile{
				{Path: "a", Lines: []string{"x"}, Size: 100, Language: "X"},
				{Path: "b", Lines: []string{"y"}, Size: 100, Language: "Y"},
				{Path: "c", Lines: []string{"z"}, Size: 50, Language: "Z"},
				{Path: "d", Lines: []string{"w"}, Size: 50, Language: "W"},
			},
			wantTotalFiles: 4,
			wantTotalLines: 4,
			wantTotalSize:  300,
			wantAvgLines:   1.0,
			wantAvgSize:    75.0,
			wantLargest:    "a",
			wantSmallest:   "c",
			wantLangs:      map[string]int{"X": 1, "Y": 1, "Z": 1, "W": 1},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := NewStatisticsCalculator()
			stats := sc.CalculateFileStats(tt.files)

			assert.NotNil(t, stats)
			assert.NotNil(t, stats.Languages)

			assert.Equal(t, tt.wantTotalFiles, stats.TotalFiles)
			assert.Equal(t, tt.wantTotalLines, stats.TotalLines)
			assert.Equal(t, tt.wantTotalSize, stats.TotalSize)
			assert.InDelta(t, tt.wantAvgLines, stats.AverageLines, 1e-9)
			assert.InDelta(t, tt.wantAvgSize, stats.AverageSize, 1e-9)
			assert.Equal(t, tt.wantLargest, stats.LargestFile)
			assert.Equal(t, tt.wantSmallest, stats.SmallestFile)
			assert.Equal(t, tt.wantLangs, stats.Languages)
		})
	}
}

func TestStatisticsCalculator_CalculateFileStats_NilReceiver(t *testing.T) {
	var sc *StatisticsCalculator // nil receiver
	files := []*CodeFile{
		{Path: "x", Lines: []string{"a", "b"}, Size: 10, Language: "Go"},
	}
	// Method does not access receiver fields, so this should not panic.
	stats := sc.CalculateFileStats(files)

	assert.NotNil(t, stats)
	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 2, stats.TotalLines)
	assert.Equal(t, 10, stats.TotalSize)
	assert.InDelta(t, 2.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 10.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "x", stats.LargestFile)
	assert.Equal(t, "x", stats.SmallestFile)
	assert.Equal(t, map[string]int{"Go": 1}, stats.Languages)
}
