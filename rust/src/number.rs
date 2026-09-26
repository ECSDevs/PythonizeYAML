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
    /// PyYAML's resolver set (YAML 1.1): the default for plain scalars.
    Yaml11,
    /// YAML 1.2 core schema, selected by an explicit `%YAML 1.2` directive.
    Yaml12,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NumberKind {
    Integer,
    Float,
    Decimal,
}

/// Largest `|exponent|` handled by the exact rational comparison in
/// [`exact_f64`]. Building `10^exponent` for anything larger would need
/// gigabytes of memory (or truncate with `as u32`), so such inputs resolve
/// through the plain f64 parse instead.
const MAX_EXACT_EXPONENT: i64 = 10_000;

pub fn strip_numeric_separators(value: &str) -> String {
    value.chars().filter(|ch| *ch != '_').collect()
}

pub fn resolve_number(value: &str, schema: SchemaVersion) -> Option<NumberKind> {
    let raw = strip_numeric_separators(value.trim());
    if raw.is_empty() {
        return None;
    }
    match schema {
        SchemaVersion::Yaml11 => {
            if is_yaml11_integer(&raw) {
                return Some(NumberKind::Integer);
            }
            if is_yaml11_float(&raw) {
                return Some(float_kind(&raw));
            }
            None
        }
        SchemaVersion::Yaml12 => {
            if is_integer_literal(&raw) {
                return Some(NumberKind::Integer);
            }
            if is_non_finite_float(&raw) {
                return Some(NumberKind::Float);
            }
            if !is_decimal_float(&raw) {
                return None;
            }
            Some(float_kind(&raw))
        }
    }
}

fn float_kind(raw: &str) -> NumberKind {
    // Sexagesimal floats fold through base-60 f64 arithmetic exactly like
    // PyYAML's constructor; the exact-representation Decimal extension only
    // applies to decimal notation.
    if raw.contains(':') {
        return NumberKind::Float;
    }
    if exact_f64(raw).is_some() {
        NumberKind::Float
    } else {
        NumberKind::Decimal
    }
}

pub fn exact_f64(value: &str) -> Option<f64> {
    let cleaned = strip_numeric_separators(value);
    let parsed = f64::from_str(&cleaned).ok()?;
    if !parsed.is_finite() {
        return None;
    }
    let decimal = BigDecimal::from_str(&cleaned).ok()?;
    // Skip the exact rational comparison for extreme exponents: building
    // 10^exponent can require gigabytes, and plain f64 parsing collapses
    // those inputs to 0.0/inf exactly like PyYAML's float() does.
    let (_, exponent) = decimal.as_bigint_and_exponent();
    if exponent.unsigned_abs() > MAX_EXACT_EXPONENT.unsigned_abs() {
        return Some(parsed);
    }
    let rational = decimal_to_rational(&decimal);
    let float = BigRational::from_float(parsed)?;
    (rational == float).then_some(parsed)
}

/// Converts an integer-classified scalar to its decimal text. The schema
/// selects the accepted literal forms: YAML 1.1 (PyYAML) treats a leading
/// zero as octal and supports sexagesimal digits, YAML 1.2 keeps `0o` octal.
pub fn integer_to_decimal_string(value: &str, schema: SchemaVersion) -> Option<String> {
    let raw = strip_numeric_separators(value.trim());
    if raw.is_empty() {
        return None;
    }
    let (sign, unsigned) = match raw.as_str() {
        _ if raw.starts_with('-') => ("-", &raw[1..]),
        _ if raw.starts_with('+') => ("", &raw[1..]),
        _ => ("", raw.as_str()),
    };
    let magnitude = match schema {
        SchemaVersion::Yaml11 => yaml11_integer_value(unsigned)?,
        SchemaVersion::Yaml12 => yaml12_integer_value(unsigned)?,
    };
    Some(format!("{sign}{magnitude}"))
}

/// PyYAML folds sexagesimal floats by accumulating base-60 digits, least
/// significant first (`1:30.5` -> `90.5`).
pub fn sexagesimal_float_value(raw: &str) -> Option<f64> {
    let unsigned = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    if !unsigned.contains(':') {
        return None;
    }
    let groups = unsigned.split(':').count();
    let mut value = 0.0f64;
    let mut base = 60f64.powi(groups as i32 - 1);
    for part in unsigned.split(':') {
        let number: f64 = part.parse().ok()?;
        value += number * base;
        base /= 60.0;
    }
    Some(if raw.starts_with('-') { -value } else { value })
}

fn yaml12_integer_value(unsigned: &str) -> Option<String> {
    if let Some(rest) = unsigned
        .strip_prefix("0x")
        .or_else(|| unsigned.strip_prefix("0X"))
    {
        return BigInt::parse_bytes(rest.as_bytes(), 16).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = unsigned
        .strip_prefix("0o")
        .or_else(|| unsigned.strip_prefix("0O"))
    {
        return BigInt::parse_bytes(rest.as_bytes(), 8).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = unsigned
        .strip_prefix("0b")
        .or_else(|| unsigned.strip_prefix("0B"))
    {
        return BigInt::parse_bytes(rest.as_bytes(), 2).map(|v| v.to_str_radix(10));
    }
    BigInt::from_str(unsigned).ok().map(|v| v.to_str_radix(10))
}

/// YAML 1.1 integer conversion per PyYAML's resolver:
/// `[-+]?0b[0-1]+` | `[-+]?0x[0-9a-fA-F]+` | `[-+]?0[0-7]+` (leading-zero
/// octal) | `[-+]?(0|[1-9][0-9]*)` | `[-+]?[1-9][0-9]*(:[0-5]?[0-9])+`.
fn yaml11_integer_value(unsigned: &str) -> Option<String> {
    if unsigned == "0" {
        return Some("0".to_owned());
    }
    if let Some(rest) = unsigned.strip_prefix("0x") {
        return BigInt::parse_bytes(rest.as_bytes(), 16).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = unsigned.strip_prefix("0b") {
        return BigInt::parse_bytes(rest.as_bytes(), 2).map(|v| v.to_str_radix(10));
    }
    if let Some(rest) = unsigned.strip_prefix('0') {
        // YAML 1.1 leading-zero octal: `052` is 42 while `09` is a string.
        let value = BigInt::parse_bytes(rest.as_bytes(), 8)?;
        return Some(value.to_str_radix(10));
    }
    if is_yaml11_sexagesimal(unsigned) {
        let mut value = BigInt::from_str(unsigned.split(':').next()?).ok()?;
        for part in unsigned.split(':').skip(1) {
            value = value * 60u32 + BigInt::from_str(part).ok()?;
        }
        return Some(value.to_str_radix(10));
    }
    let bytes = unsigned.as_bytes();
    if !bytes.is_empty() && bytes[0].is_ascii_digit() && bytes.iter().all(|b| b.is_ascii_digit()) {
        return BigInt::from_str(unsigned).ok().map(|v| v.to_str_radix(10));
    }
    None
}

/// PyYAML's YAML 1.1 int resolver shapes (underscores already stripped).
fn is_yaml11_integer(raw: &str) -> bool {
    let unsigned = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    if let Some(rest) = unsigned.strip_prefix("0b") {
        return !rest.is_empty() && rest.bytes().all(|byte| matches!(byte, b'0' | b'1'));
    }
    if let Some(rest) = unsigned.strip_prefix("0x") {
        return !rest.is_empty() && rest.bytes().all(|byte| byte.is_ascii_hexdigit());
    }
    if unsigned == "0" {
        return true;
    }
    if let Some(rest) = unsigned.strip_prefix('0') {
        return !rest.is_empty() && rest.bytes().all(|byte| matches!(byte, b'0'..=b'7'));
    }
    if is_yaml11_sexagesimal(unsigned) {
        return true;
    }
    let bytes = unsigned.as_bytes();
    !bytes.is_empty() && bytes[0].is_ascii_digit() && bytes.iter().all(|byte| byte.is_ascii_digit())
}

/// `[-+]?[1-9][0-9]*(:[0-5]?[0-9])+` — the minute groups must stay below 60,
/// so `1:60` is not a number (PyYAML leaves it a string).
fn is_yaml11_sexagesimal(unsigned: &str) -> bool {
    let mut parts = unsigned.split(':');
    let Some(first) = parts.next() else {
        return false;
    };
    let first = first.as_bytes();
    if first.is_empty() || first[0] == b'0' || !first.iter().all(|byte| byte.is_ascii_digit()) {
        return false;
    }
    let mut groups = 0usize;
    for part in parts {
        if !is_sexagesimal_minute(part) {
            return false;
        }
        groups += 1;
    }
    groups > 0
}

fn is_sexagesimal_minute(part: &str) -> bool {
    let bytes = part.as_bytes();
    match bytes.len() {
        1 => bytes[0].is_ascii_digit(),
        2 => bytes[0].is_ascii_digit() && bytes[1].is_ascii_digit() && bytes[0] <= b'5',
        _ => false,
    }
}

/// PyYAML's YAML 1.1 float resolver: the decimal point is mandatory, an
/// exponent needs an explicit sign (`1.5e3` stays a string), and
/// `[-+]?[0-9]+(:[0-5]?[0-9])+\.[0-9]*` is a sexagesimal float.
fn is_yaml11_float(raw: &str) -> bool {
    if matches!(
        raw,
        ".inf"
            | ".Inf"
            | ".INF"
            | "+.inf"
            | "+.Inf"
            | "+.INF"
            | "-.inf"
            | "-.Inf"
            | "-.INF"
            | ".nan"
            | ".NaN"
            | ".NAN"
    ) {
        return true;
    }
    let unsigned = raw.strip_prefix(['+', '-']).unwrap_or(raw);
    if unsigned.contains(':') {
        return is_yaml11_sexagesimal_float(unsigned);
    }
    let (mantissa, exponent) = match unsigned.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => (mantissa, Some(exponent)),
        None => (unsigned, None),
    };
    if let Some(exponent) = exponent {
        let bytes = exponent.as_bytes();
        if bytes.len() < 2
            || (bytes[0] != b'+' && bytes[0] != b'-')
            || !bytes[1..].iter().all(|byte| byte.is_ascii_digit())
        {
            return false;
        }
    }
    is_yaml11_decimal_mantissa(mantissa)
}

fn is_yaml11_decimal_mantissa(mantissa: &str) -> bool {
    let Some((int_part, frac_part)) = mantissa.split_once('.') else {
        return false;
    };
    if int_part.is_empty() && frac_part.is_empty() {
        return false;
    }
    int_part.bytes().all(|byte| byte.is_ascii_digit())
        && frac_part.bytes().all(|byte| byte.is_ascii_digit())
}

fn is_yaml11_sexagesimal_float(unsigned: &str) -> bool {
    let parts: Vec<&str> = unsigned.split(':').collect();
    if parts.len() < 2 {
        return false;
    }
    let head = parts[0];
    if head.is_empty() || !head.bytes().all(|byte| byte.is_ascii_digit()) {
        return false;
    }
    for part in &parts[1..parts.len() - 1] {
        if !is_sexagesimal_minute(part) {
            return false;
        }
    }
    // The last group carries the mandatory decimal point: `1:30.5`.
    let Some((minute_part, rest)) = parts[parts.len() - 1].split_once('.') else {
        return false;
    };
    if !is_sexagesimal_minute(minute_part) {
        return false;
    }
    let (frac, exponent) = match rest.split_once(['e', 'E']) {
        Some((frac, exponent)) => (frac, Some(exponent)),
        None => (rest, None),
    };
    if !frac.bytes().all(|byte| byte.is_ascii_digit()) {
        return false;
    }
    match exponent {
        None => true,
        Some(exponent) => {
            let bytes = exponent.as_bytes();
            bytes.len() >= 2
                && (bytes[0] == b'+' || bytes[0] == b'-')
                && bytes[1..].iter().all(|byte| byte.is_ascii_digit())
        }
    }
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
        assert_eq!(
            integer_to_decimal_string("0xff", SchemaVersion::Yaml11),
            Some("255".to_owned())
        );
        assert_eq!(
            integer_to_decimal_string("123456789012345678901234567890", SchemaVersion::Yaml11),
            Some("123456789012345678901234567890".to_owned())
        );
    }

    #[test]
    fn huge_exponents_skip_the_exact_rational_check() {
        // These used to build a 10^5000000000 BigInt (or truncate `as u32`).
        assert_eq!(exact_f64("1.0e-5000000000"), Some(0.0));
        assert_eq!(exact_f64("1.0e+5000000000"), None);
        assert_eq!(
            resolve_number("1.0e-5000000000", SchemaVersion::Yaml11),
            Some(NumberKind::Float)
        );
        // A f64-infinitely-large value still falls back to Decimal.
        assert_eq!(
            resolve_number("1.0e+400", SchemaVersion::Yaml11),
            Some(NumberKind::Decimal)
        );
    }

    #[test]
    fn yaml11_leading_zero_integers_are_octal() {
        assert_eq!(
            resolve_number("052", SchemaVersion::Yaml11),
            Some(NumberKind::Integer)
        );
        assert_eq!(
            integer_to_decimal_string("052", SchemaVersion::Yaml11),
            Some("42".to_owned())
        );
        assert_eq!(
            integer_to_decimal_string("00", SchemaVersion::Yaml11),
            Some("0".to_owned())
        );
        // `09` cannot be octal or decimal under YAML 1.1.
        assert_eq!(resolve_number("09", SchemaVersion::Yaml11), None);
        // The 0o prefix is YAML 1.2 only.
        assert_eq!(resolve_number("0o17", SchemaVersion::Yaml11), None);
        assert_eq!(
            resolve_number("0o17", SchemaVersion::Yaml12),
            Some(NumberKind::Integer)
        );
        assert_eq!(
            integer_to_decimal_string("052", SchemaVersion::Yaml12),
            Some("52".to_owned())
        );
    }

    #[test]
    fn yaml11_sexagesimal_integers_convert_to_decimal() {
        assert_eq!(
            integer_to_decimal_string("22:00", SchemaVersion::Yaml11),
            Some("1320".to_owned())
        );
        assert_eq!(
            integer_to_decimal_string("-1:30", SchemaVersion::Yaml11),
            Some("-90".to_owned())
        );
        assert_eq!(
            integer_to_decimal_string("+1:5", SchemaVersion::Yaml11),
            Some("65".to_owned())
        );
        assert_eq!(
            integer_to_decimal_string("190:20:30", SchemaVersion::Yaml11),
            Some("685230".to_owned())
        );
        // Minute groups must stay below 60.
        assert_eq!(
            integer_to_decimal_string("1:60", SchemaVersion::Yaml11),
            None
        );
        // The first group must not carry a leading zero.
        assert_eq!(
            integer_to_decimal_string("0:30", SchemaVersion::Yaml11),
            None
        );
        // Sexagesimal is YAML 1.1 only.
        assert_eq!(
            integer_to_decimal_string("22:00", SchemaVersion::Yaml12),
            None
        );
    }

    #[test]
    fn yaml11_floats_need_a_point_and_signed_exponents() {
        assert_eq!(
            resolve_number("1.5e+3", SchemaVersion::Yaml11),
            Some(NumberKind::Float)
        );
        // Unsigned exponents stay strings, like PyYAML.
        assert_eq!(resolve_number("1.5e3", SchemaVersion::Yaml11), None);
        assert_eq!(
            resolve_number(".5", SchemaVersion::Yaml11),
            Some(NumberKind::Float)
        );
        assert_eq!(
            resolve_number("1.", SchemaVersion::Yaml11),
            Some(NumberKind::Float)
        );
        assert_eq!(resolve_number("1e400", SchemaVersion::Yaml11), None);
    }

    #[test]
    fn yaml11_sexagesimal_floats_fold_base_sixty() {
        assert_eq!(
            resolve_number("1:30.5", SchemaVersion::Yaml11),
            Some(NumberKind::Float)
        );
        assert_eq!(sexagesimal_float_value("1:30.5"), Some(90.5));
        assert_eq!(sexagesimal_float_value("-1:30.5"), Some(-90.5));
        assert_eq!(sexagesimal_float_value("190:20:30.15"), Some(685230.15));
        // Without the point it is an integer, not a float.
        assert_eq!(
            resolve_number("1:30", SchemaVersion::Yaml11),
            Some(NumberKind::Integer)
        );
        assert_eq!(resolve_number("1:60.5", SchemaVersion::Yaml11), None);
    }
}
