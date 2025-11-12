RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |arg| arg }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 422 when validation fails' do
      error_double = double(to_hash: { field: 'content', message: 'is required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_double])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Validation failed')
      expect(json_response['details']).to eq([{ 'field' => 'content', 'message' => 'is required' }])
    end

    it 'detects language from path and forwards to python service' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |arg| arg }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => [] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'python', content: 'print(1)'), anything)
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: 'print(1)', path: 'script.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'GET /status' do
    it 'returns aggregated services status' do
      go_status = { status: 'healthy' }
      py_status = { status: 'unreachable', error: 'timeout' }

      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health).and_return(go_status, py_status)

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['ruby']).to eq({ 'status' => 'healthy' })
      expect(json['services']['go']).to eq(go_status.transform_keys(&:to_s))
      expect(json['services']['python']).to eq(py_status.transform_keys(&:to_s))
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review when both contents are provided' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'changes' => 3 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 88.0, 'issues' => [] })

      payload = { old_content: 'a', new_content: 'b' }
      post '/diff', payload.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']).to eq({ 'changes' => 3 })
      expect(json['new_code_review']).to eq({ 'score' => 88.0, 'issues' => [] })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'returns metrics, review and overall_quality score' do
      metrics = { 'complexity' => 2 }
      review  = { 'score' => 90, 'issues' => ['a'] }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'hello'))
        .and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'hello'))
        .and_return(review)

      post '/metrics', { content: 'hello' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to eq(metrics)
      expect(json['review']).to eq(review)
      expect(json['overall_quality']).to eq(20.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and summary' do
      fixed_time = Time.at(1_600_000_000)
      allow(Time).to receive(:now).and_return(fixed_time)

      file_stats = {
        'total_files' => 2,
        'total_lines' => 100,
        'languages' => { 'ruby' => 1, 'python' => 1 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 3,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: array_including('a.rb', 'b.py')))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: array_including('a.rb', 'b.py')))
        .and_return(review_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:calculate_dashboard_health_score)
        .with(file_stats, review_stats)
        .and_return(65.5)

      post '/dashboard', { files: ['a.rb', 'b.py'] }.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['timestamp']).to eq(fixed_time.iso8601)
      expect(json['file_statistics']).to eq(file_stats)
      expect(json['review_statistics']).to eq(review_stats)
      expect(json['summary']).to include(
        'total_files' => 2,
        'total_lines' => 100,
        'languages' => { 'ruby' => 1, 'python' => 1 },
        'average_quality_score' => 80.0,
        'total_issues' => 3,
        'health_score' => 65.5
      )
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [{ 'id' => '1' }, { 'id' => '2' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

      get '/traces/abc'
      expect(last_response.status).to eq(404)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for the given correlation id' do
      traces = [{ 'step' => 'start' }, { 'step' => 'end' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(traces)

      get '/traces/xyz'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('xyz')
      expect(json['trace_count']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'validation errors endpoints' do
    it 'GET /validation/errors returns stored errors' do
      errors = [{ field: 'content', message: 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_errors']).to eq(1)
      expect(json['errors']).to eq([errors.first.transform_keys(&:to_s)])
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['message']).to eq('Validation errors cleared')
    end
  end

  describe 'private utility methods' do
    let(:instance) { described_class.new }

    describe '#detect_language' do
      it 'returns language based on file extension' do
        expect(instance.send(:detect_language, 'file.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'test.py')).to eq('python')
        expect(instance.send(:detect_language, 'main.go')).to eq('go')
        expect(instance.send(:detect_language, 'script.js')).to eq('javascript')
        expect(instance.send(:detect_language, 'types.ts')).to eq('typescript')
        expect(instance.send(:detect_language, 'Program.java')).to eq('java')
        expect(instance.send(:detect_language, 'README')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics or review is missing or contains error' do
        expect(instance.send(:calculate_quality_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_quality_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_quality_score, { 'error' => 'x' }, {})).to eq(0.0)
        expect(instance.send(:calculate_quality_score, {}, { 'error' => 'x' })).to eq(0.0)
      end

      it 'calculates score with penalties and clamps to 0' do
        metrics = { 'complexity' => 10 }
        review = { 'score' => 50, 'issues' => %w[a b c] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(0)
      end

      it 'calculates and clamps to 100 when above' do
        metrics = { 'complexity' => 0 }
        review = { 'score' => 120, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(100)
      end

      it 'calculates a normal positive score' do
        metrics = { 'complexity' => 2 }
        review = { 'score' => 90, 'issues' => ['x'] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(20.0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when inputs are missing or contain errors' do
        expect(instance.send(:calculate_dashboard_health_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, { 'error' => 'x' }, {})).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, {}, { 'error' => 'x' })).to eq(0.0)
      end

      it 'calculates health score and clamps within 0..100' do
        file_stats = { 'total_files' => 5 }
        review_stats = { 'average_score' => 80,
                         'total_issues' => 10, 'average_complexity' => 0.5 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(61.0)

        file_stats2 = { 'total_files' => 1 }
        review_stats2 = { 'average_score' => 10,
                          'total_issues' => 100, 'average_complexity' => 2 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats2, review_stats2)).to eq(0.0)

        file_stats3 = { 'total_files' => 10 }
        review_stats3 = { 'average_score' => 120,
                          'total_issues' => 0, 'average_complexity' => 0 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats3, review_stats3)).to eq(100.0)
      end
    end
  end
end
