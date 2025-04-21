#include <stdio.h>

int idx(char* str) {
    int i = str[0];
    return i;
}

int main() {
    int t = idx("\0abcd");
    printf("%i\n", t);
    int x = 14/4;
    printf("%d\n", x);
}
