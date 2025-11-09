package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func newCodeFile(path, lang string, size, lines int) *CodeFile {
	content := make([]string, lines)
	for i := 0; i < lines; i++ {
		content[i] = "line"
	}
	return &CodeFile{
		Path:     path,
		Language: lang,
		Size:     size,
		Lines:    content,
	}
}

func TestNewStatisticsCalculator(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)
}

func TestStatisticsCalculator_CalculateFileStats(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)

	tests := []struct {
		name          string
		files         []*CodeFile
		wantFiles     int
		wantLines     int
		wantSize      int
		wantAvgLines  float64
		wantAvgSize   float64
		wantLargest   string
		wantSmallest  string
		wantLanguages map[string]int
	}{
		{
			name:          "empty input",
			files:         nil,
			wantFiles:     0,
			wantLines:     0,
			wantSize:      0,
			wantAvgLines:  0,
			wantAvgSize:   0,
			wantLargest:   "",
			wantSmallest:  "",
			wantLanguages: map[string]int{},
		},
		{
			name: "single file",
			files: []*CodeFile{
				newCodeFile("file.txt", "Text", 42, 3),
			},
			wantFiles:     1,
			wantLines:     3,
			wantSize:      42,
			wantAvgLines:  3.0,
			wantAvgSize:   42.0,
			wantLargest:   "file.txt",
			wantSmallest:  "file.txt",
			wantLanguages: map[string]int{"Text": 1},
		},
		{
			name: "multiple files with different sizes and languages",
			files: []*CodeFile{
				newCodeFile("a.go", "Go", 100, 10),
				newCodeFile("b.py", "Python", 200, 20),
				newCodeFile("c.js", "JavaScript", 50, 5),
			},
			wantFiles:     3,
			wantLines:     35,          // 10 + 20 + 5
			wantSize:      350,         // 100 + 200 + 50
			wantAvgLines:  35.0 / 3.0,  // 11.666...
			wantAvgSize:   350.0 / 3.0, // 116.666...
			wantLargest:   "b.py",
			wantSmallest:  "c.js",
			wantLanguages: map[string]int{"Go": 1, "Python": 1, "JavaScript": 1},
		},
		{
			name: "language aggregation and smallest tie behavior",
			files: []*CodeFile{
				newCodeFile("a.go", "Go", 10, 1),
				newCodeFile("b.go", "Go", 20, 2),
				newCodeFile("c.py", "Python", 5, 3),
				newCodeFile("d.go", "Go", 5, 4), // tie for smallest with c.py, should not replace
			},
			wantFiles:     4,
			wantLines:     10,     // 1 + 2 + 3 + 4
			wantSize:      40,     // 10 + 20 + 5 + 5
			wantAvgLines:  2.5,    // 10 / 4
			wantAvgSize:   10.0,   // 40 / 4
			wantLargest:   "b.go", // size 20
			wantSmallest:  "c.py", // first min at size 5
			wantLanguages: map[string]int{"Go": 3, "Python": 1},
		},
		{
			name: "all sizes equal - largest and smallest remain first file",
			files: []*CodeFile{
				newCodeFile("x1", "tie", 100, 1),
				newCodeFile("x2", "tie", 100, 2),
				newCodeFile("x3", "tie", 100, 3),
			},
			wantFiles:     3,
			wantLines:     6,    // 1 + 2 + 3
			wantSize:      300,  // 100 * 3
			wantAvgLines:  2.0,  // 6 / 3
			wantAvgSize:   100., // 300 / 3
			wantLargest:   "x1",
			wantSmallest:  "x1",
			wantLanguages: map[string]int{"tie": 3},
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			stats := calc.CalculateFileStats(tt.files)
			assert.NotNil(t, stats)

			assert.Equal(t, tt.wantFiles, stats.TotalFiles)
			assert.Equal(t, tt.wantLines, stats.TotalLines)
			assert.Equal(t, tt.wantSize, stats.TotalSize)
			assert.InDelta(t, tt.wantAvgLines, stats.AverageLines, 1e-9)
			assert.InDelta(t, tt.wantAvgSize, stats.AverageSize, 1e-9)
			assert.Equal(t, tt.wantLargest, stats.LargestFile)
			assert.Equal(t, tt.wantSmallest, stats.SmallestFile)

			// Languages map should not be nil
			assert.NotNil(t, stats.Languages)
			assert.Equal(t, tt.wantLanguages, stats.Languages)
		})
	}
}
