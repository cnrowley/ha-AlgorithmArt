package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"image"
	"image/color"
	"math"
	"os"
	"strings"

	"golang.org/x/image/bmp"
)

type ColorName string

const (
	ColorWhite  ColorName = "white"
	ColorBlack  ColorName = "black"
	ColorRed    ColorName = "red"
	ColorGreen  ColorName = "green"
	ColorBlue   ColorName = "blue"
	ColorYellow ColorName = "yellow"
)

type Pattern string

const (
	PatternHoneycomb    Pattern = "honeycomb"
	PatternHexDots      Pattern = "hexdots"
	PatternLines        Pattern = "lines"
	PatternSquare       Pattern = "square"
	PatternTriangular   Pattern = "triangular"
	PatternKagome       Pattern = "kagome"
	PatternCircles      Pattern = "circles"
	PatternSpokes       Pattern = "spokes"
	PatternCheckerboard Pattern = "checkerboard"
)

type State struct {
	Iteration int     `json:"iteration"`
	Rotation  float64 `json:"rotation_deg"`
	TX        float64 `json:"tx"`
	TY        float64 `json:"ty"`
	Scale     float64 `json:"scale"`
	Pattern   string  `json:"pattern"`
}

type Config struct {
	Pattern    Pattern
	Width      int
	Height     int
	Rotation   float64
	TX         float64
	TY         float64
	Scale      float64
	Background ColorName
	LineColor  ColorName
	Output     string
	Animate    bool
	Iteration  int
	StatePath  string
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}

func run() error {
	cfg := parseFlags()

	if err := validateConfig(cfg); err != nil {
		return err
	}

	if cfg.Animate {
		i := float64(cfg.Iteration)
		cfg.Rotation = 1.2 + 0.015*i
		cfg.TX = 3 * math.Sin(i/20)
		cfg.TY = 3 * math.Cos(i/23)
		cfg.Scale = math.Pow(1.00015, i)
	}

	img := image.NewRGBA(image.Rect(0, 0, cfg.Width, cfg.Height))
	fill(img, toRGBA(cfg.Background))

	line := toRGBA(cfg.LineColor)

	switch cfg.Pattern {
	case PatternHoneycomb:
		drawHoneycomb(img, cfg, line)
	case PatternHexDots:
		drawHexDots(img, cfg, line)
	case PatternLines:
		drawLines(img, cfg, line)
	case PatternSquare:
		drawSquare(img, cfg, line)
	case PatternTriangular:
		drawTriangular(img, cfg, line)
	case PatternKagome:
		drawKagome(img, cfg, line)
	case PatternCircles:
		drawCircles(img, cfg, line)
	case PatternSpokes:
		drawSpokes(img, cfg, line)
	case PatternCheckerboard:
		drawCheckerboard(img, cfg, line)
	default:
		return fmt.Errorf("unsupported pattern %q", cfg.Pattern)
	}

	if err := writeBMP(cfg.Output, img); err != nil {
		return err
	}

	state := State{
		Iteration: cfg.Iteration,
		Rotation:  cfg.Rotation,
		TX:        cfg.TX,
		TY:        cfg.TY,
		Scale:     cfg.Scale,
		Pattern:   string(cfg.Pattern),
	}

	if err := writeState(cfg.StatePath, state); err != nil {
		return err
	}

	fmt.Printf("Pattern: %s\n", cfg.Pattern)
	fmt.Printf("Output: %s\n", cfg.Output)
	fmt.Printf("State: %s\n", cfg.StatePath)
	fmt.Printf("Iteration: %d\n", cfg.Iteration)

	return nil
}

func parseFlags() Config {
	cfg := Config{}

	pattern := flag.String("pattern", string(PatternHoneycomb), "pattern: honeycomb, hexdots, lines, square, triangular, kagome, circles, spokes, checkerboard")
	background := flag.String("background", string(ColorWhite), "background color: white, black, red, green, blue, yellow")
	linecolor := flag.String("linecolor", string(ColorBlack), "line color: white, black, red, green, blue, yellow")

	flag.IntVar(&cfg.Width, "width", 800, "image width in pixels")
	flag.IntVar(&cfg.Height, "height", 480, "image height in pixels")
	flag.Float64Var(&cfg.Rotation, "rotation", 1.2, "overlay rotation in degrees")
	flag.Float64Var(&cfg.TX, "tx", 5, "overlay translation x in pixels")
	flag.Float64Var(&cfg.TY, "ty", 0, "overlay translation y in pixels")
	flag.Float64Var(&cfg.Scale, "scale", 1.0, "overlay scale")
	flag.StringVar(&cfg.Output, "output", "current.bmp", "output BMP path")
	flag.BoolVar(&cfg.Animate, "animate", false, "enable deterministic animation mode")
	flag.IntVar(&cfg.Iteration, "iteration", 0, "animation iteration")
	flag.StringVar(&cfg.StatePath, "state", "moire_state.json", "output JSON state path")

	flag.Parse()

	cfg.Pattern = Pattern(strings.ToLower(strings.TrimSpace(*pattern)))
	cfg.Background = ColorName(strings.ToLower(strings.TrimSpace(*background)))
	cfg.LineColor = ColorName(strings.ToLower(strings.TrimSpace(*linecolor)))

	return cfg
}

func validateConfig(cfg Config) error {
	if cfg.Width <= 0 || cfg.Height <= 0 {
		return fmt.Errorf("dimensions must be positive, got width=%d height=%d", cfg.Width, cfg.Height)
	}
	if cfg.Width > 20000 || cfg.Height > 20000 {
		return fmt.Errorf("dimensions are too large, got width=%d height=%d", cfg.Width, cfg.Height)
	}
	if !validPattern(cfg.Pattern) {
		return fmt.Errorf("invalid pattern %q", cfg.Pattern)
	}
	if !validColor(cfg.Background) {
		return fmt.Errorf("invalid background color %q", cfg.Background)
	}
	if !validColor(cfg.LineColor) {
		return fmt.Errorf("invalid line color %q", cfg.LineColor)
	}
	if cfg.Scale <= 0 || math.IsNaN(cfg.Scale) || math.IsInf(cfg.Scale, 0) {
		return fmt.Errorf("scale must be a finite positive number, got %g", cfg.Scale)
	}
	if math.IsNaN(cfg.Rotation) || math.IsInf(cfg.Rotation, 0) {
		return fmt.Errorf("rotation must be finite, got %g", cfg.Rotation)
	}
	if math.IsNaN(cfg.TX) || math.IsInf(cfg.TX, 0) || math.IsNaN(cfg.TY) || math.IsInf(cfg.TY, 0) {
		return fmt.Errorf("translation must be finite, got tx=%g ty=%g", cfg.TX, cfg.TY)
	}
	if strings.TrimSpace(cfg.Output) == "" {
		return errors.New("output path must not be empty")
	}
	if strings.TrimSpace(cfg.StatePath) == "" {
		return errors.New("state path must not be empty")
	}
	return nil
}

func validPattern(p Pattern) bool {
	switch p {
	case PatternHoneycomb, PatternHexDots, PatternLines, PatternSquare, PatternTriangular, PatternKagome, PatternCircles, PatternSpokes, PatternCheckerboard:
		return true
	default:
		return false
	}
}

func validColor(c ColorName) bool {
	switch c {
	case ColorWhite, ColorBlack, ColorRed, ColorGreen, ColorBlue, ColorYellow:
		return true
	default:
		return false
	}
}

func toRGBA(name ColorName) color.RGBA {
	switch name {
	case ColorWhite:
		return color.RGBA{R: 255, G: 255, B: 255, A: 255}
	case ColorBlack:
		return color.RGBA{R: 0, G: 0, B: 0, A: 255}
	case ColorRed:
		return color.RGBA{R: 255, G: 0, B: 0, A: 255}
	case ColorGreen:
		return color.RGBA{R: 0, G: 170, B: 0, A: 255}
	case ColorBlue:
		return color.RGBA{R: 0, G: 0, B: 255, A: 255}
	case ColorYellow:
		return color.RGBA{R: 255, G: 255, B: 0, A: 255}
	default:
		return color.RGBA{R: 0, G: 0, B: 0, A: 255}
	}
}

func fill(img *image.RGBA, col color.RGBA) {
	b := img.Bounds()
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			img.SetRGBA(x, y, col)
		}
	}
}

func writeBMP(path string, img image.Image) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create BMP %q: %w", path, err)
	}
	defer func() {
		_ = f.Close()
	}()

	if err := bmp.Encode(f, img); err != nil {
		return fmt.Errorf("encode BMP %q: %w", path, err)
	}

	return nil
}

func writeState(path string, state State) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal state: %w", err)
	}
	data = append(data, '\n')

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("write state %q: %w", path, err)
	}

	return nil
}

func transform(x, y, rotDeg, tx, ty, scale float64) (float64, float64) {
	x *= scale
	y *= scale

	t := rotDeg * math.Pi / 180
	c := math.Cos(t)
	s := math.Sin(t)

	xx := c*x - s*y + tx
	yy := s*x + c*y + ty

	return xx, yy
}

func plotThick(img *image.RGBA, x, y, radius int, col color.RGBA) {
	if radius < 0 {
		return
	}

	b := img.Bounds()
	rr := radius * radius

	for dy := -radius; dy <= radius; dy++ {
		for dx := -radius; dx <= radius; dx++ {
			if dx*dx+dy*dy > rr {
				continue
			}
			px := x + dx
			py := y + dy
			if px >= b.Min.X && px < b.Max.X && py >= b.Min.Y && py < b.Max.Y {
				img.SetRGBA(px, py, col)
			}
		}
	}
}

func drawLine(img *image.RGBA, x0, y0, x1, y1 int, radius int, col color.RGBA) {
	dx := absInt(x1 - x0)
	dy := -absInt(y1 - y0)

	sx := -1
	if x0 < x1 {
		sx = 1
	}

	sy := -1
	if y0 < y1 {
		sy = 1
	}

	err := dx + dy

	for {
		plotThick(img, x0, y0, radius, col)

		if x0 == x1 && y0 == y1 {
			return
		}

		e2 := 2 * err

		if e2 >= dy {
			err += dy
			x0 += sx
		}

		if e2 <= dx {
			err += dx
			y0 += sy
		}
	}
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

func round(v float64) int {
	return int(math.Round(v))
}

func drawSegment(img *image.RGBA, cfg Config, x1, y1, x2, y2 float64, radius int, col color.RGBA, transformed bool) {
	if transformed {
		x1, y1 = transform(x1, y1, cfg.Rotation, cfg.TX, cfg.TY, cfg.Scale)
		x2, y2 = transform(x2, y2, cfg.Rotation, cfg.TX, cfg.TY, cfg.Scale)
	}

	cx := float64(cfg.Width) / 2
	cy := float64(cfg.Height) / 2

	drawLine(img, round(x1+cx), round(y1+cy), round(x2+cx), round(y2+cy), radius, col)
}

func drawSegmentPair(img *image.RGBA, cfg Config, x1, y1, x2, y2 float64, radius int, col color.RGBA) {
	drawSegment(img, cfg, x1, y1, x2, y2, radius, col, false)
	drawSegment(img, cfg, x1, y1, x2, y2, radius, col, true)
}

func drawPoint(img *image.RGBA, cfg Config, x, y float64, radius int, col color.RGBA, transformed bool) {
	if transformed {
		x, y = transform(x, y, cfg.Rotation, cfg.TX, cfg.TY, cfg.Scale)
	}

	cx := float64(cfg.Width) / 2
	cy := float64(cfg.Height) / 2

	plotThick(img, round(x+cx), round(y+cy), radius, col)
}

func drawPointPair(img *image.RGBA, cfg Config, x, y float64, radius int, col color.RGBA) {
	drawPoint(img, cfg, x, y, radius, col, false)
	drawPoint(img, cfg, x, y, radius, col, true)
}

func coverageRadius(cfg Config) float64 {
	return math.Hypot(float64(cfg.Width), float64(cfg.Height))*0.75 + 200
}

func drawLines(img *image.RGBA, cfg Config, col color.RGBA) {
	spacing := 40.0
	r := coverageRadius(cfg)

	for x := -r; x <= r; x += spacing {
		drawSegmentPair(img, cfg, x, -r, x, r, 2, col)
	}
}

func drawSquare(img *image.RGBA, cfg Config, col color.RGBA) {
	spacing := 50.0
	r := coverageRadius(cfg)

	for x := -r; x <= r; x += spacing {
		drawSegmentPair(img, cfg, x, -r, x, r, 2, col)
	}
	for y := -r; y <= r; y += spacing {
		drawSegmentPair(img, cfg, -r, y, r, y, 2, col)
	}
}

func drawHexDots(img *image.RGBA, cfg Config, col color.RGBA) {
	spacing := 40.0
	rowH := math.Sqrt(3) * spacing / 2
	r := coverageRadius(cfg)

	row := 0
	for y := -r; y <= r; y += rowH {
		shift := 0.0
		if row%2 != 0 {
			shift = spacing / 2
		}
		for x := -r; x <= r; x += spacing {
			drawPointPair(img, cfg, x+shift, y, 3, col)
		}
		row++
	}
}

func drawHoneycomb(img *image.RGBA, cfg Config, col color.RGBA) {
	cellsAcross := 20.0
	bond := float64(cfg.Width) / (cellsAcross * math.Sqrt(3))
	sqrt3 := math.Sqrt(3)

	a1x := sqrt3 * bond
	a1y := 0.0
	a2x := sqrt3 * bond / 2
	a2y := 1.5 * bond

	neighbors := [][2]float64{
		{0, bond},
		{-sqrt3 * bond / 2, -bond / 2},
		{sqrt3 * bond / 2, -bond / 2},
	}

	r := coverageRadius(cfg)
	n := int(math.Ceil(r/bond)) + 8

	for i := -n; i <= n; i++ {
		for j := -n; j <= n; j++ {
			ax := float64(i)*a1x + float64(j)*a2x
			ay := float64(i)*a1y + float64(j)*a2y

			if math.Abs(ax) > r+2*bond || math.Abs(ay) > r+2*bond {
				continue
			}

			for _, d := range neighbors {
				drawSegmentPair(img, cfg, ax, ay, ax+d[0], ay+d[1], 2, col)
			}
		}
	}
}

func drawTriangular(img *image.RGBA, cfg Config, col color.RGBA) {
	s := 40.0
	h := math.Sqrt(3) * s / 2
	r := coverageRadius(cfg)

	rows := int(math.Ceil(2*r/h)) + 4
	cols := int(math.Ceil(2*r/s)) + 4

	for row := -rows; row <= rows; row++ {
		y := float64(row) * h
		shift := 0.0
		if row%2 != 0 {
			shift = s / 2
		}

		for colIdx := -cols; colIdx <= cols; colIdx++ {
			x := float64(colIdx)*s + shift
			drawSegmentPair(img, cfg, x, y, x+s, y, 2, col)
			drawSegmentPair(img, cfg, x, y, x+s/2, y+h, 2, col)
			drawSegmentPair(img, cfg, x+s, y, x+s/2, y+h, 2, col)
		}
	}
}

func drawKagome(img *image.RGBA, cfg Config, col color.RGBA) {
	s := 45.0
	sqrt3 := math.Sqrt(3)

	a1x := s
	a1y := 0.0
	a2x := s / 2
	a2y := sqrt3 * s / 2

	p0 := [2]float64{0, 0}
	p1 := [2]float64{s / 2, 0}
	p2 := [2]float64{s / 4, sqrt3 * s / 4}

	r := coverageRadius(cfg)
	n := int(math.Ceil(r/s)) + 10

	for i := -n; i <= n; i++ {
		for j := -n; j <= n; j++ {
			ox := float64(i)*a1x + float64(j)*a2x
			oy := float64(i)*a1y + float64(j)*a2y

			if math.Abs(ox) > r+2*s || math.Abs(oy) > r+2*s {
				continue
			}

			cell := [][2][2]float64{
				{{ox + p0[0], oy + p0[1]}, {ox + p1[0], oy + p1[1]}},
				{{ox + p1[0], oy + p1[1]}, {ox + p2[0], oy + p2[1]}},
				{{ox + p2[0], oy + p2[1]}, {ox + p0[0], oy + p0[1]}},
				{{ox + p1[0], oy + p1[1]}, {ox + s + p0[0], oy + p0[1]}},
				{{ox + p2[0], oy + p2[1]}, {ox + a2x + p0[0], oy + a2y + p0[1]}},
				{{ox + p2[0], oy + p2[1]}, {ox + a2x - s/2 + p1[0], oy + a2y + p1[1]}},
			}

			for _, seg := range cell {
				drawSegmentPair(img, cfg, seg[0][0], seg[0][1], seg[1][0], seg[1][1], 2, col)
			}
		}
	}
}

func drawCircles(img *image.RGBA, cfg Config, col color.RGBA) {
	spacing := 28.0
	maxR := coverageRadius(cfg)
	step := 0.012

	for r := spacing; r <= maxR; r += spacing {
		prevX := r
		prevY := 0.0

		for th := step; th <= 2*math.Pi+step; th += step {
			x := r * math.Cos(th)
			y := r * math.Sin(th)

			drawSegmentPair(img, cfg, prevX, prevY, x, y, 2, col)

			prevX = x
			prevY = y
		}
	}
}

func drawSpokes(img *image.RGBA, cfg Config, col color.RGBA) {
	count := 96
	r := coverageRadius(cfg)

	for k := 0; k < count; k++ {
		t := 2 * math.Pi * float64(k) / float64(count)
		drawSegmentPair(img, cfg, 0, 0, r*math.Cos(t), r*math.Sin(t), 2, col)
	}
}

func drawCheckerboard(img *image.RGBA, cfg Config, col color.RGBA) {
	cell := 40.0
	r := coverageRadius(cfg)

	for y := -r; y < r; y += cell {
		for x := -r; x < r; x += cell {
			ix := int(math.Floor(x / cell))
			iy := int(math.Floor(y / cell))
			if (ix+iy)&1 == 0 {
				fillSquare(img, cfg, x, y, cell, col, false)
				fillSquare(img, cfg, x, y, cell, col, true)
			}
		}
	}
}

func fillSquare(img *image.RGBA, cfg Config, x, y, size float64, col color.RGBA, transformed bool) {
	step := 1.0
	cx := float64(cfg.Width) / 2
	cy := float64(cfg.Height) / 2

	for yy := y; yy < y+size; yy += step {
		for xx := x; xx < x+size; xx += step {
			px := xx
			py := yy
			if transformed {
				px, py = transform(px, py, cfg.Rotation, cfg.TX, cfg.TY, cfg.Scale)
			}
			plotThick(img, round(px+cx), round(py+cy), 0, col)
		}
	}
}
