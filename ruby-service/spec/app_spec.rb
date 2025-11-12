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
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'returns aggregated service statuses' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8080').and_return({ status: 'healthy' })
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with('http://localhost:8081').and_return({ status: 'unreachable' })

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['ruby']['status']).to eq('healthy')
      expect(json['services']['go']['status']).to eq('healthy')
      expect(json['services']['python']['status']).to eq('unreachable')
    end
  end

  describe 'POST /analyze validations and headers' do
    it 'returns 422 when validation fails' do
      error_double = double('ValidationError', to_hash: { field: 'content', message: 'required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_double])

      expect_any_instance_of(PolyglotAPI).not_to receive(:call_go_service)
      expect_any_instance_of(PolyglotAPI).not_to receive(:call_python_service)

      post '/analyze', { path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Validation failed')
      expect(json['details']).to include(hash_including('field' => 'content'))
    end

    it 'propagates correlation id to downstream services and returns it' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |val| val }

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'code', path: 'foo.rb'), 'cid-123')
        .and_return({ 'language' => 'ruby', 'lines' => [] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code', language: 'ruby'), 'cid-123')
        .and_return({ 'score' => 99, 'issues' => [] })

      post '/analyze',
           { content: 'code', path: 'foo.rb' }.to_json,
           { 'CONTENT_TYPE' => 'application/json', CorrelationIdMiddleware::CORRELATION_ID_HEADER => 'cid-123' }

      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('cid-123')
      expect(json['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when missing contents' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and review for valid request' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', { old_content: 'a', new_content: 'b' })
        .and_return({ 'changes' => 1 })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', { content: 'b' })
        .and_return({ 'score' => 50, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']['changes']).to eq(1)
      expect(json['new_code_review']['score']).to eq(50)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and overall quality score' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', { content: 'abc' })
        .and_return({ 'complexity' => 1 })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', { content: 'abc' })
        .and_return({ 'score' => 90, 'issues' => ['x'] })

      post '/metrics', { content: 'abc' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']['complexity']).to eq(1)
      expect(json['review']['score']).to eq(90)
      expect(json['overall_quality']).to be_within(0.01).of(30.0)
    end

    it 'returns overall_quality 0 when services return errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', { content: 'boom' })
        .and_return({ 'error' => 'timeout' })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', { content: 'boom' })
        .and_return({ 'score' => 85, 'issues' => [] })

      post '/metrics', { content: 'boom' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']['error']).to eq('timeout')
      expect(json['overall_quality']).to eq(0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files are missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end

    it 'returns aggregated dashboard statistics and health score' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.rb', 'content' => 'puts 2' }]

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', { files: files })
        .and_return({ 'total_files' => 2, 'total_lines' => 100, 'languages' => { 'ruby' => 2 } })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', { files: files })
        .and_return({ 'average_score' => 80.0, 'total_issues' => 10, 'average_complexity' => 0.5 })

      fixed_time = Time.utc(2020, 1, 1, 0, 0, 0)
      allow(Time).to receive(:now).and_return(fixed_time)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['timestamp']).to eq(fixed_time.iso8601)
      expect(json['summary']['total_files']).to eq(2)
      expect(json['summary']['total_lines']).to eq(100)
      expect(json['summary']['average_quality_score']).to eq(80.0)
      expect(json['summary']['health_score']).to be_within(0.01).of(55.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return([{ 'id' => '1' }, { 'id' => '2' }])

      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces'].length).to eq(2)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('missing').and_return([])

      get '/traces/missing'
      expect(last_response.status).to eq(404)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for a given correlation id' do
      traces = [{ 'event' => 'a' }, { 'event' => 'b' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('cid-1').and_return(traces)

      get '/traces/cid-1'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('cid-1')
      expect(json['trace_count']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'validation errors endpoints' do
    it 'GET /validation/errors returns error list' do
      allow(RequestValidator).to receive(:get_validation_errors)
        .and_return([{ 'field' => 'content', 'message' => 'missing' }])

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_errors']).to eq(1)
      expect(json['errors'].length).to eq(1)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['message']).to eq('Validation errors cleared')
    end
  end
end
