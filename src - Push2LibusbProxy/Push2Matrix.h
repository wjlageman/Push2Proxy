#ifndef PUSH2MATRIX_H
#define PUSH2MATRIX_H

template <typename T>
class Push2Matrix {
public:
    static constexpr int WIDTH = 960;
    static constexpr int HEIGHT = 160;

    Push2Matrix() {
        data = new T[WIDTH * HEIGHT];
    }

    ~Push2Matrix() {
        delete[] data;
    }

    // Disable copy constructor and assignment.
    Push2Matrix(const Push2Matrix&) = delete;
    Push2Matrix& operator=(const Push2Matrix&) = delete;

    inline T& at(int x, int y) {
        // Optionally add bounds checking
        return data[y * WIDTH + x];
    }
    inline const T& at(int x, int y) const {
        return data[y * WIDTH + x];
    }

    // Public accessor for the underlying data pointer.
    inline T* getData() { return data; }
    inline const T* getData() const { return data; }

    // Fill the matrix with a given value.
    void fill(const T& value) {
        for (int i = 0; i < WIDTH * HEIGHT; i++) {
            data[i] = value;
        }
    }

    inline int getWidth() const { return WIDTH; }
    inline int getHeight() const { return HEIGHT; }

private:
    T* data;
};

#endif // PUSH2MATRIX_H
