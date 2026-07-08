package main

import (
    "encoding/binary"
    "encoding/json"
    "flag"
    "fmt"
    "math"
    "os"
    "path/filepath"
)

// ------------------------------------------------------------
// Defaults (match display)
// ------------------------------------------------------------

const (
    DefaultWidth  = 800
    DefaultHeight = 480

    MinVariance = 0.002
    MinGradient = 0.010
    MaxZoom     = 1e11
)

// ------------------------------------------------------------
// ACeP palette
// ------------------------------------------------------------

const (
    BLACK  = 0
    WHITE  = 1
    GREEN  = 2
    BLUE   = 3
    RED    = 4
    YELLOW = 5
    ORANGE = 6
)

type BGRA struct {
    B, G, R, A uint8
}

var acepPalette = []BGRA{
    {0, 0, 0, 0},       // BLACK
    {255, 255, 255, 0}, // WHITE
    {0, 255, 0, 0},     // GREEN
    {255, 0, 0, 0},     // BLUE
    {0, 0, 255, 0},     // RED
    {0, 255, 255, 0},   // YELLOW
    {0, 165, 255, 0},   // ORANGE
}

// ------------------------------------------------------------
// Persistent generator state
// ------------------------------------------------------------

type GeneratorState struct {
    CX    float64 `json:"cx"`
    CY    float64 `json:"cy"`
    Zoom  float64 `json:"zoom"`
    Frame int     `json:"frame"`
}

func loadState(path string) (*GeneratorState, error) {
    b, err := os.ReadFile(path)
    if err != nil {
        return nil, err
    }

    var s GeneratorState
    if err := json.Unmarshal(b, &s); err != nil {
        return nil, err
    }

    return &s, nil
}

func saveState(path string, s *GeneratorState) error {
    tmp := path + ".tmp"

    b, err := json.MarshalIndent(s, "", "  ")
    if err != nil {
        return err
    }

    if err := os.WriteFile(tmp, b, 0644); err != nil {
        return err
    }

    return os.Rename(tmp, path)
}

// ------------------------------------------------------------
// Mandelbrot render
// ------------------------------------------------------------

func render(
    out []uint8,
    width, height int,
    state *GeneratorState,
    maxIter int,
    fg, bg uint8,
) (variance, gradient float64) {

    n := width * height
    nu := make([]float64, n)

    scale := 4.0 / (float64(width) * state.Zoom)
    x0 := state.CX - float64(width)*0.5*scale
    y0 := state.CY - float64(height)*0.5*scale

    var mean, mean2 float64

    for y := 0; y < height; y++ {
        ci := y0 + float64(y)*scale

        for x := 0; x < width; x++ {
            cr := x0 + float64(x)*scale

            zr, zi := 0.0, 0.0
            zr2, zi2 := 0.0, 0.0
            iter := 0

            for zr2+zi2 < 16.0 && iter < maxIter {
                zi = 2*zr*zi + ci
                zr = zr2 - zi2 + cr
                zr2 = zr * zr
                zi2 = zi * zi
                iter++
            }

            v := 0.0
            if iter < maxIter {
                v = float64(iter) + 1.0 -
                    math.Log2(math.Log(math.Sqrt(zr2+zi2)))
            }

            i := y*width + x
            nu[i] = v
            mean += v
            mean2 += v * v
        }
    }

    mean /= float64(n)
    mean2 /= float64(n)
    variance = mean2 - mean*mean

    for y := 1; y < height-1; y++ {
        for x := 1; x < width-1; x++ {
            i := y*width + x

            dx := nu[i+1] - nu[i-1]
            dy := nu[i+width] - nu[i-width]

            gradient += math.Hypot(dx, dy)
        }
    }

    gradient /= float64(n)

    for i := 0; i < n; i++ {
        if nu[i] > mean {
            out[i] = fg
        } else {
            out[i] = bg
        }
    }

    return
}

// ------------------------------------------------------------
// BMP writer, 24-bit truecolor, atomic
//
// The internal framebuffer remains []uint8 palette indices.
// The BMP file is expanded to 24-bit BGR pixels for compatibility
// with the ESP32 photo frame firmware.
//
// This matches the style of your working DLA renderer:
//   - 54-byte BMP header
//   - no palette
//   - 24 bits per pixel
//   - bottom-up rows
//   - rows padded to 4-byte boundaries
// ------------------------------------------------------------

func writeBMPAtomic(path string, pixels []uint8, width, height int) error {
    tmp := path + ".tmp"

    rowSize := (3*width + 3) &^ 3
    imgSize := rowSize * height
    fileSize := 14 + 40 + imgSize

    f, err := os.Create(tmp)
    if err != nil {
        return err
    }

    closeAndRemove := func() {
        _ = f.Close()
        _ = os.Remove(tmp)
    }

    // --------------------------------------------------------
    // BMP file header, 14 bytes
    // --------------------------------------------------------

    if err := binary.Write(f, binary.LittleEndian, uint16(0x4D42)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint32(fileSize)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint16(0)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint16(0)); err != nil {
        closeAndRemove()
        return err
    }

    // Pixel data starts immediately after the 14-byte file header
    // and 40-byte BITMAPINFOHEADER.
    if err := binary.Write(f, binary.LittleEndian, uint32(14+40)); err != nil {
        closeAndRemove()
        return err
    }

    // --------------------------------------------------------
    // DIB header, BITMAPINFOHEADER, 40 bytes
    // --------------------------------------------------------

    if err := binary.Write(f, binary.LittleEndian, uint32(40)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, int32(width)); err != nil {
        closeAndRemove()
        return err
    }

    // Positive height means bottom-up BMP.
    if err := binary.Write(f, binary.LittleEndian, int32(height)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint16(1)); err != nil {
        closeAndRemove()
        return err
    }

    // 24 bits per pixel.
    if err := binary.Write(f, binary.LittleEndian, uint16(24)); err != nil {
        closeAndRemove()
        return err
    }

    // BI_RGB, no compression.
    if err := binary.Write(f, binary.LittleEndian, uint32(0)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint32(imgSize)); err != nil {
        closeAndRemove()
        return err
    }

    // Pixels per metre. 2835 is approximately 72 DPI.
    if err := binary.Write(f, binary.LittleEndian, int32(2835)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, int32(2835)); err != nil {
        closeAndRemove()
        return err
    }

    // No palette.
    if err := binary.Write(f, binary.LittleEndian, uint32(0)); err != nil {
        closeAndRemove()
        return err
    }

    if err := binary.Write(f, binary.LittleEndian, uint32(0)); err != nil {
        closeAndRemove()
        return err
    }

    // --------------------------------------------------------
    // Pixel data
    // --------------------------------------------------------

    row := make([]byte, rowSize)

    // Bottom-up: write last image row first.
    for y := height - 1; y >= 0; y-- {
        i := 0

        for x := 0; x < width; x++ {
            paletteIndex := pixels[y*width+x]

            var c BGRA
            if int(paletteIndex) < len(acepPalette) {
                c = acepPalette[paletteIndex]
            } else {
                c = acepPalette[BLACK]
            }

            row[i] = c.B
            row[i+1] = c.G
            row[i+2] = c.R
            i += 3
        }

        // Pad row to 4-byte boundary.
        for ; i < rowSize; i++ {
            row[i] = 0
        }

        if _, err := f.Write(row); err != nil {
            closeAndRemove()
            return err
        }
    }

    if err := f.Close(); err != nil {
        _ = os.Remove(tmp)
        return err
    }

    return os.Rename(tmp, path)
}

// ------------------------------------------------------------
// Main
// ------------------------------------------------------------

func main() {
    width := flag.Int("width", DefaultWidth, "image width")
    height := flag.Int("height", DefaultHeight, "image height")
    outDir := flag.String("out", "out", "output directory")
    frames := flag.Int("frames", 1, "number of frames, ignored with --single")
    single := flag.Bool("single", false, "generate exactly one frame")
    statePath := flag.String("state", "", "state JSON file")

    fgName := flag.String("fg", "white", "foreground color")
    bgName := flag.String("bg", "black", "background color")

    flag.Parse()

    colorMap := map[string]uint8{
        "black":  BLACK,
        "white":  WHITE,
        "green":  GREEN,
        "blue":   BLUE,
        "red":    RED,
        "yellow": YELLOW,
        "orange": ORANGE,
    }

    fg, ok1 := colorMap[*fgName]
    bg, ok2 := colorMap[*bgName]

    if !ok1 || !ok2 {
        fmt.Fprintln(os.Stderr, "Invalid color name")
        os.Exit(1)
    }

    if err := os.MkdirAll(*outDir, 0755); err != nil {
        fmt.Fprintln(os.Stderr, "Failed to create output directory:", err)
        os.Exit(1)
    }

    // Load or initialize state.
    var state *GeneratorState

    if *statePath != "" {
        if s, err := loadState(*statePath); err == nil {
            state = s
        }
    }

    if state == nil {
        state = &GeneratorState{
            CX:    -0.743643887037158,
            CY:    0.131825904205311,
            Zoom:  100.0,
            Frame: 0,
        }
    }

    frameBuf := make([]uint8, (*width)*(*height))

    count := *frames
    if *single {
        count = 1
    }

    for i := 0; i < count; i++ {
        if state.Zoom > MaxZoom {
            os.Exit(10)
        }

        maxIter := int(math.Min(
            4096,
            math.Max(
                256,
                256+math.Pow(math.Log10(state.Zoom), 1.6)*120,
            ),
        ))

        variance, gradient := render(
            frameBuf,
            *width,
            *height,
            state,
            maxIter,
            fg,
            bg,
        )

        fmt.Printf(
            "Frame %d zoom=%g var=%g grad=%g\n",
            state.Frame,
            state.Zoom,
            variance,
            gradient,
        )

        if variance < MinVariance || gradient < MinGradient {
            fmt.Println("Structure exhausted — stopping")
            os.Exit(10)
        }

        outFile := filepath.Join(*outDir, "current.bmp")

        if err := writeBMPAtomic(outFile, frameBuf, *width, *height); err != nil {
            fmt.Fprintln(os.Stderr, "write error:", err)
            os.Exit(20)
        }

        state.Zoom *= 1.25
        state.Frame++

        if *statePath != "" {
            if err := saveState(*statePath, state); err != nil {
                fmt.Fprintln(os.Stderr, "state save error:", err)
                os.Exit(30)
            }
        }
    }
}


