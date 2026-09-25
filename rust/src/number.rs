// Copyright (c) 2026 PythonizeYAML contributors
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

use bigdecimal::BigDecimal;
use num_bigint::{BigInt, Sign};
use num_rational::BigRational;
use num_traits::{Signed, Zero};
use std::str::FromStr;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SchemaVersion {
    Yaml12,
    Yaml11,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NumberKind {
    Integer,
    Float,
    Decimal,
}

pub fn strip_numeric_separators(value: &str) -> String {
    value.chars().filter(|ch| *ch != '_').collect()
}

pub fn resolve_number(value: &str, schema: SchemaVersion) -> Option<NumberKind> {
    let raw = strip_numeric_separators(value.trim());
    if raw.is_empty() {
        return None;
    }
    if is_integer_literal(&raw) {
        return Some(NumberKind::Integer);
    }
    if schema == SchemaVersion::Yaml11 && is_legacy_sexagesimal(&raw) {
        return Some(NumberKind::Integer);
    }
    if is_non_finite_float(&raw) {
        return Some(NumberKind::Float);
    }
    if !is_decimal_float(&raw) {
        return None;
    }
    if exact_f64(&raw).is_some() {
        Some(NumberKind::Float)
    } else {
        Some(NumberKind::Decimal)
    }
}

pub fn exact_f64(value: &str) -> Option<f64> {
    let parsed = f64::from_str(&strip_numeric_separators(value)).ok()?;
    if !parsed.is_finite() {
        return None;
    }
    let decimal = BigDecimal::from_str(&strip_numeric_separators(value)).ok()?;
    let rational = decimal_to_rational(&decimal);
    let float = BigRational::from_float(parsed)?;
    (rational == float).then_some(parsed)
}

pub fn integer_to_decimal_string(value: &str) -> Option<String> {
    let raw = strip_numeric_separators(value.trim());
    if raw.is_empty() {
        return None;
    }
    if let Some(rest) = raw.strip_prefix(['+', '-']) {
        let sign = if raw.starts_with('-') { "-" } else { "" };
        return integer_to_decimal_string(rest).map(|v| format!("{sign}{v}"));
    }
    if let Some(rest) = raw.strip_prefix("0x").or_else(|| raw.strip_prefix("0X")) {
        return BigInt::parse_bytes(rest.as_bytes(), 16).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = raw.strip_prefix("0o").or_else(|| raw.strip_prefix("0O")) {
        return BigInt::parse_bytes(rest.as_bytes(), 8).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = raw.strip_prefix("0b").or_else(|| raw.strip_prefix("0B")) {
        return BigInt::parse_bytes(rest.as_bytes(), 2).map(|v| v.to_str_radix(10));
    }
    BigInt::from_str(&raw).ok().map(|v| v.to_str_radix(10))
}

fn is_integer_literal(raw: &str) -> bool {
    let unsigned = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    if unsigned == "0" {
        return true;
    }
    if let Some(rest) = unsigned
        .strip_prefix("0x")
        .or_else(|| unsigned.strip_prefix("0X"))
    {
        return !rest.is_empty() && rest.chars().all(|ch| ch.is_ascii_hexdigit());
    }
    if let Some(rest) = unsigned
        .strip_prefix("0o")
        .or_else(|| unsigned.strip_prefix("0O"))
    {
        return !rest.is_empty() && rest.chars().all(|ch| matches!(ch, '0'..='7'));
    }
    if let Some(rest) = unsigned
        .strip_prefix("0b")
        .or_else(|| unsigned.strip_prefix("0B"))
    {
        return !rest.is_empty() && rest.chars().all(|ch| matches!(ch, '0' | '1'));
    }
    !unsigned.is_empty() && unsigned.chars().all(|ch| ch.is_ascii_digit())
}

fn is_non_finite_float(raw: &str) -> bool {
    matches!(
        raw.to_ascii_lowercase().as_str(),
        ".inf" | "+.inf" | "-.inf" | ".nan"
    )
}

fn is_decimal_float(raw: &str) -> bool {
    let mut chars = raw.chars().peekable();
    if matches!(chars.peek(), Some('+') | Some('-')) {
        chars.next();
    }
    let mut digits = 0usize;
    while matches!(chars.peek(), Some(ch) if ch.is_ascii_digit()) {
        digits += 1;
        chars.next();
    }
    let mut fraction_digits = 0usize;
    if chars.peek() == Some(&'.') {
        chars.next();
        while matches!(chars.peek(), Some(ch) if ch.is_ascii_digit()) {
            fraction_digits += 1;
            chars.next();
        }
    }
    if digits + fraction_digits == 0 {
        return false;
    }
    if matches!(chars.peek(), Some('e') | Some('E')) {
        chars.next();
        if matches!(chars.peek(), Some('+') | Some('-')) {
            chars.next();
        }
        let mut exponent_digits = 0usize;
        while matches!(chars.peek(), Some(ch) if ch.is_ascii_digit()) {
            exponent_digits += 1;
            chars.next();
        }
        if exponent_digits == 0 {
            return false;
        }
    }
    chars.next().is_none()
}

fn is_legacy_sexagesimal(raw: &str) -> bool {
    let value = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    let parts: Vec<_> = value.split(':').collect();
    parts.len() > 1
        && parts
            .iter()
            .all(|part| !part.is_empty() && part.chars().all(|ch| ch.is_ascii_digit()))
}

fn decimal_to_rational(decimal: &BigDecimal) -> BigRational {
    let (coefficient, exponent) = decimal.as_bigint_and_exponent();
    if exponent >= 0 {
        let scale = BigInt::from(10u8).pow(exponent as u32);
        BigRational::new(coefficient, scale)
    } else {
        let scale = BigInt::from(10u8).pow((-exponent) as u32);
        BigRational::from_integer(coefficient * scale)
    }
}

#[allow(dead_code)]
fn _touch_signs(value: &BigInt) -> (Sign, bool, bool) {
    (value.sign(), value.is_zero(), value.is_negative())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exactly_representable_decimals_stay_float() {
        assert_eq!(exact_f64("1.5"), Some(1.5));
        assert_eq!(exact_f64("2.0"), Some(2.0));
    }

    #[test]
    fn inexact_decimal_values_require_decimal() {
        assert!(exact_f64("0.1").is_none());
        assert!(exact_f64("1e400").is_none());
        assert_eq!(
            resolve_number("0.1", SchemaVersion::Yaml12),
            Some(NumberKind::Decimal)
        );
    }

    #[test]
    fn integers_are_normalized_without_width_limits() {
        assert_eq!(integer_to_decimal_string("0xff"), Some("255".to_owned()));
        assert_eq!(
            integer_to_decimal_string("123456789012345678901234567890"),
            Some("123456789012345678901234567890".to_owned())
        );
    }
}
