# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID: `R-seeded_regression-C-002-s11` |
| Triệu chứng | Grader Lab 8 fail với lý do: `status resolved != denied`. Kết quả ghi nhận `refund_vnd=20000`, `refund_count=1` trong khi nhãn kỳ vọng `refund_vnd=0`, `refund_count=0`, status `denied`. |
| Bước sai đầu tiên | **Event #3: `model_override`** với payload `{"delay_days": 5}`. |
| Vì sao là bước *đầu tiên* | Ở Event #1 (`handoff`) và Event #2 (`investigator`), hệ thống tra cứu DB đúng: đơn hàng O-202 có `delay_days = 1`. Tuy nhiên tại Event #3, agent đã tự ý ghi đè số ngày trễ của DB thành 5 ngày theo lời khai trong ticket của khách hàng (`ticket_trust`). |
| Failure mode | **FM-03 (`ticket_trust`)** — tin ticket hơn DB |
| Đối chứng | Cùng claim `C-002@11` trên shape `fixed`: Không có event `model_override` nào. DB fact `delay_days = 1` được giữ nguyên, dẫn tới Event #3 `quote` trả về `amount_vnd = 0, reason = no_entitlement`, kết quả status `denied`, ledger `refund_vnd = 0` hoàn toàn trùng khớp với nhãn. |
| Regression test | Grader `DbFactKept` (kiểm tra không có sự kiện `model_override`), và `test_lab9_graders.py::test_override_event_breaks_db_fact`. Đã xác nhận: test fail trên `seeded_regression` và pass trên `fixed`. |
| Chưa chắc chắn | Trace chỉ ghi nhận hành vi override sau khi complete model; không thể phân biệt được model bị ảo giác (hallucination) hay bị prompt injection cố ý nếu không có log chi tiết của tokenizer. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
