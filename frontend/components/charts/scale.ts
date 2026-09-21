// Escala "redonda" para o eixo Y dos gráficos (1, 2, 5 ou 10 × potência de 10).
// Mínimo de 4 para que poucos dados não produzam um eixo de 0 a 1.
export function niceMax(max: number): number {
  if (max <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(max));
  const n = max / pow;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return nice * pow;
}
