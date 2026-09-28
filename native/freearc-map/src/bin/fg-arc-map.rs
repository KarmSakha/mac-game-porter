//! CLI: emit a JSON map of every solid block (absolute offset, size,
//! method chain) and its files, for an external streaming extractor.
use std::fs::File;
use std::path::PathBuf;
use std::process::ExitCode;

use cellar_freearc_native::{dir, footer::block_type, open, read_control_block};

fn esc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

fn main() -> ExitCode {
    let path: PathBuf = match std::env::args().nth(1) {
        Some(p) => p.into(),
        None => { eprintln!("usage: fg-arc-map <archive>"); return ExitCode::from(2); }
    };
    let mut f = File::open(&path).expect("open archive");
    let summary = open(&mut f).expect("read footer");
    let mut blocks = Vec::new();
    for entry in summary.control_blocks.iter().filter(|e| e.block_type == block_type::DIR) {
        let dir_pos = summary.footer.block_pos.checked_sub(entry.rel_pos).expect("dir pos");
        let raw = read_control_block(&mut f, &summary.footer, entry).expect("read dir block");
        let parsed = dir::parse(&raw).expect("parse dir block");
        let mut idx = 0usize;
        for sb in &parsed.solid_blocks {
            let n = sb.n_files as usize;
            let files: Vec<String> = parsed.files[idx..idx + n].iter().map(|fe| {
                format!("{{\"path\":\"{}\",\"size\":{},\"crc\":{},\"dir\":{}}}",
                        esc(&parsed.full_path(fe)), fe.size, fe.crc, fe.is_dir)
            }).collect();
            idx += n;
            let offset = dir_pos.checked_sub(sb.rel_pos).expect("solid pos");
            blocks.push(format!("{{\"method\":\"{}\",\"offset\":{},\"compsize\":{},\"files\":[{}]}}",
                                esc(&sb.compressor), offset, sb.compsize, files.join(",")));
        }
    }
    println!("{{\"blocks\":[{}]}}", blocks.join(","));
    ExitCode::SUCCESS
}
