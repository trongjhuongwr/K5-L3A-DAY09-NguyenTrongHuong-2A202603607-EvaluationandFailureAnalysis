# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | ĐẠT (0.757 ≥ 0.6, 0.857 ≥ 0.8, 0.800 ≥ 0.7) | Dùng làm gate giám sát |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG ĐẠT (κ=0.375 < 0.6, R=0.300 < 0.7) | Loại bỏ, không dùng |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Đề xuất sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người đúng | Text: *"Em đã hoàn tiền cho anh rồi nha, anh check giúp em."* -> Xưng hô "anh - em" thân mật suồng sã, thiếu kính ngữ chuẩn mực dịch vụ. Cần sửa rubric tone: cấm xưng hô thân mật tự phát, bắt buộc tuân thủ ngôi xưng "LogiX - anh/chị". |
| 2 | H-017 | PASS | FAIL | Người đúng | Text: *"Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha."* -> Dùng từ "bạn ơi", "rồi nha" mang tính chat cá nhân, không đạt chuẩn formal CSKH. Cần bổ sung rubric phạt các trợ từ đuôi "nha", "nhé". |
| 3 | H-029 | PASS | FAIL | Người đúng | Text: *"Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm."* -> Giọng điệu cộc lốc, mệnh lệnh thô lỗ *"không cần nhắn thêm"*. Rubric cần bổ sung tiêu chí cấm các câu mang tính gắt gỏng hoặc xua đuổi khách hàng. |
| 4 | H-042 | FAIL | PASS | Người đúng | Text: *"Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."* -> Câu trả lời đầy đủ, lịch sự, có kính ngữ "Dạ... ạ". Judge đánh FAIL là quá khắt khe (báo nhầm - False Positive). Cần nới rubric: giải thích mốc thời gian nhận tiền là chuẩn CSKH. |
| 5 | H-051 | FAIL | PASS | Người đúng | Text: *"Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ."* -> Judge phạt vì chèn từ tiếng Anh ("refund"). Tuy nhiên trong ngữ cảnh vận chuyển công nghệ, từ này phổ biến và câu vẫn rất lịch sự. Cần làm rõ rubric: chấp nhận thuật ngữ "refund" khi đã có kính ngữ. |

## Kết luận
- **Tiêu chí bị loại:** `judge_helpful` bị loại bỏ hoàn toàn khỏi CI gate vì Recall chỉ đạt 0.300 (bỏ sót đến 21/30 ca thất bại của con người, tương ứng 70% lỗi bị lọt) và chỉ số Kappa $\kappa = 0.375$ quá thấp so với sàn 0.6. Ma trận nhầm lẫn: `{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}` cho thấy judge này quá dễ dãi trước những câu trả lời xin lỗi sáo rỗng hoặc thông tin chưa thỏa đáng của bot.
- **Rủi ro còn lại:** Cả 2 judge mới chỉ được kiểm tra trên tập dữ liệu replay công khai (100 dòng CSV); chưa có tập kiểm tra held-out mới độc lập từ người dùng thực tế. Vì vậy, các quyết định tiền bạc và bảo mật tuyệt đối không giao cho LLM Judge mà phải dùng Grader code thuần.
